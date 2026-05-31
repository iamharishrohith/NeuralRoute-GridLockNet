import pandas as pd
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from sklearn.preprocessing import LabelEncoder, StandardScaler
import os
import copy

# Set seed for reproducibility
np.random.seed(42)
torch.manual_seed(42)

def r2_score_numpy(y_true, y_pred):
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    r2 = 1 - ss_res / (ss_tot + 1e-8)
    return r2

# Custom PyTorch Dataset
class TrafficDataset(Dataset):
    def __init__(self, cat_features, cont_features, targets=None):
        self.cat_features = torch.tensor(cat_features, dtype=torch.long)
        self.cont_features = torch.tensor(cont_features, dtype=torch.float32)
        self.targets = torch.tensor(targets, dtype=torch.float32) if targets is not None else None

    def __len__(self):
        return len(self.cat_features)

    def __getitem__(self, idx):
        if self.targets is not None:
            return self.cat_features[idx], self.cont_features[idx], self.targets[idx]
        return self.cat_features[idx], self.cont_features[idx]

# GridLockNet: Custom Spatial-Temporal Tabular ResNet
class GridLockNet(nn.Module):
    def __init__(self, cat_dims, emb_dims, num_cont_features):
        super(GridLockNet, self).__init__()
        
        # 1. Learnable embeddings for categoricals
        self.embeddings = nn.ModuleList([
            nn.Embedding(num_embeddings=dim, embedding_dim=emb_dim)
            for dim, emb_dim in zip(cat_dims, emb_dims)
        ])
        
        total_emb_dim = sum(emb_dims)
        
        # 2. Continuous feature processing branch
        self.cont_mlp = nn.Sequential(
            nn.Linear(num_cont_features, 64),
            nn.BatchNorm1d(64),
            nn.GELU(),
            nn.Linear(64, 32),
            nn.BatchNorm1d(32),
            nn.GELU()
        )
        
        # Total dimension after combining embeddings and continuous branch
        fusion_dim = total_emb_dim + 32
        
        # 3. Tabular ResNet Core
        self.res_block1 = nn.Sequential(
            nn.Linear(fusion_dim, fusion_dim),
            nn.BatchNorm1d(fusion_dim),
            nn.GELU(),
            nn.Dropout(0.3),
            nn.Linear(fusion_dim, fusion_dim),
            nn.Dropout(0.3)
        )
        
        self.res_block2 = nn.Sequential(
            nn.Linear(fusion_dim, fusion_dim),
            nn.BatchNorm1d(fusion_dim),
            nn.GELU(),
            nn.Dropout(0.3),
            nn.Linear(fusion_dim, fusion_dim),
            nn.Dropout(0.3)
        )
        
        # 4. Output Head
        self.output_head = nn.Sequential(
            nn.Linear(fusion_dim, 32),
            nn.GELU(),
            nn.Linear(32, 1)
        )
        
    def forward(self, cat_x, cont_x):
        # Embed each categorical feature
        embedded = [emb(cat_x[:, i]) for i, emb in enumerate(self.embeddings)]
        cat_fusion = torch.cat(embedded, dim=1)
        
        # Process continuous features
        cont_features = self.cont_mlp(cont_x)
        
        # Concatenate branches
        fused = torch.cat([cat_fusion, cont_features], dim=1)
        
        # Pass through residual blocks
        fused = fused + self.res_block1(fused)
        fused = fused + self.res_block2(fused)
        
        # Output with Sigmoid activation to bound the predictions strictly in [0.0, 1.0]
        output = torch.sigmoid(self.output_head(fused)).squeeze()
        return output

def main():
    print("--- Loading Preprocessed Clean Datasets ---")
    train_df = pd.read_csv("train_clean.csv")
    test_df = pd.read_csv("test_clean.csv")
    
    # Apply min_of_day to both
    def extract_minutes(t_str):
        h, m = map(int, t_str.split(':'))
        return h * 60 + m
    
    train_df['min_of_day'] = train_df['timestamp'].apply(extract_minutes)
    test_df['min_of_day'] = test_df['timestamp'].apply(extract_minutes)
    
    # Calculate cyclic time features
    for df in [train_df, test_df]:
        df['sin_time'] = np.sin(2 * np.pi * df['min_of_day'] / 1440.0)
        df['cos_time'] = np.cos(2 * np.pi * df['min_of_day'] / 1440.0)
        
    # Extract unique geohashes
    unique_geos = list(set(train_df['geohash'].unique()).union(set(test_df['geohash'].unique())))
    print(f"Total unique geohashes: {len(unique_geos)}")
    
    # Build complete timestamps list for master grid
    day48_mins = [m for m in range(0, 1440, 15)]
    day48_timestamps = [(48, m) for m in day48_mins]
    day49_mins = [m for m in range(0, 840, 15)] # up to 13:45 (825 mins)
    day49_timestamps = [(49, m) for m in day49_mins]
    
    all_timestamps = day48_timestamps + day49_timestamps
    
    # Build master grid for autoregressive lag lookup
    print("\n--- Initializing Autoregressive 3D Master Grid ---")
    grid_records = []
    for gh in unique_geos:
        for day, mins in all_timestamps:
            grid_records.append({
                'geohash': gh,
                'day': day,
                'min_of_day': mins,
                'demand': 0.0 # Default value representing empty road / baseline
            })
    grid_df = pd.DataFrame(grid_records)
    
    # Populate the grid with true training demands
    # First set MultiIndex on grid_df for fast lookups
    grid_df.set_index(['geohash', 'day', 'min_of_day'], inplace=True)
    
    train_idx = list(zip(train_df['geohash'], train_df['day'], train_df['min_of_day']))
    grid_df.loc[train_idx, 'demand'] = train_df['demand'].values
    
    # ----------------- Step 1: Pre-compute lags for training set -----------------
    print("\n--- Pre-computing Lags for Train Set ---")
    # To compute lags correctly for train, we temporarily compute them on the sorted grid
    grid_df_sorted = grid_df.reset_index().sort_values(by=['geohash', 'day', 'min_of_day']).reset_index(drop=True)
    
    lag_shifts = {
        'lag_15m': 1, 'lag_30m': 2, 'lag_45m': 3, 'lag_1h': 4, 'lag_2h': 8, 'lag_24h': 96
    }
    for name, shift in lag_shifts.items():
        grid_df_sorted[name] = grid_df_sorted.groupby('geohash')['demand'].shift(shift)
        
    grid_df_sorted['rolling_mean_1h'] = grid_df_sorted.groupby('geohash')['demand'].transform(lambda x: x.shift(1).rolling(4, min_periods=1).mean())
    grid_df_sorted['rolling_max_1h'] = grid_df_sorted.groupby('geohash')['demand'].transform(lambda x: x.shift(1).rolling(4, min_periods=1).max())
    grid_df_sorted['rolling_std_1h'] = grid_df_sorted.groupby('geohash')['demand'].transform(lambda x: x.shift(1).rolling(4, min_periods=1).std())
    
    fill_cols = list(lag_shifts.keys()) + ['rolling_mean_1h', 'rolling_max_1h', 'rolling_std_1h']
    grid_df_sorted[fill_cols] = grid_df_sorted[fill_cols].fillna(0.0)
    
    # Merge lags back to train_df
    train_df = train_df.merge(grid_df_sorted[['geohash', 'day', 'min_of_day'] + fill_cols], 
                            on=['geohash', 'day', 'min_of_day'], how='left')
    
    # Define categorical and continuous columns
    cat_cols = ['geohash', 'geohash_pref5', 'geohash_pref4', 'geohash_pref3', 
                'RoadType', 'NumberofLanes', 'LargeVehicles', 'Landmarks', 'Weather']
    
    cont_cols = ['day', 'Temperature', 'sin_time', 'cos_time', 
                 'lag_15m', 'lag_30m', 'lag_45m', 'lag_1h', 'lag_2h', 'lag_24h', 
                 'rolling_mean_1h', 'rolling_max_1h', 'rolling_std_1h']
    
    print("\n--- Fitting Label Encoders (Leakage-Free) ---")
    combined_df = pd.concat([train_df[cat_cols], test_df[cat_cols]], axis=0, ignore_index=True)
    
    cat_dims = []
    emb_dims = []
    emb_dim_map = {
        'geohash': 64, 'geohash_pref5': 32, 'geohash_pref4': 16, 'geohash_pref3': 8,
        'RoadType': 8, 'NumberofLanes': 8, 'LargeVehicles': 4, 'Landmarks': 4, 'Weather': 4
    }
    
    label_encoders = {}
    for col in cat_cols:
        le = LabelEncoder()
        le.fit(combined_df[col].astype(str))
        train_df[col] = le.transform(train_df[col].astype(str))
        test_df[col] = le.transform(test_df[col].astype(str))
        label_encoders[col] = le
        
        cardinality = len(le.classes_)
        cat_dims.append(cardinality)
        emb_dims.append(emb_dim_map[col])
        print(f"Column '{col}' cardinality: {cardinality} -> Embedding dim: {emb_dim_map[col]}")
        
    print("\n--- Scaling Continuous Columns (Leakage-Free) ---")
    train_df['day_orig'] = train_df['day'].copy()
    test_df['day_orig'] = test_df['day'].copy()
    scaler = StandardScaler()
    train_df[cont_cols] = scaler.fit_transform(train_df[cont_cols])
    
    # ----------------- Step 2: Split Train and Validation Folds -----------------
    val_mask = train_df['day'] > train_df['day'].min()
    train_split = train_df[~val_mask].copy()
    val_split = train_df[val_mask].copy()
    
    print(f"\n--- Splitting Datasets ---")
    print(f"Train records (Day 48): {train_split.shape[0]}")
    print(f"Validation records (Day 49 early): {val_split.shape[0]}")
    
    train_dataset = TrafficDataset(train_split[cat_cols].values, train_split[cont_cols].values, train_split['demand'].values)
    val_dataset = TrafficDataset(val_split[cat_cols].values, val_split[cont_cols].values, val_split['demand'].values)
    
    train_loader = DataLoader(train_dataset, batch_size=256, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=256, shuffle=False)
    
    # ----------------- Step 3: PyTorch Model Training with Deepcopy -----------------
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"\nInitializing GridLockNet on device: {device}")
    model = GridLockNet(cat_dims, emb_dims, len(cont_cols)).to(device)
    
    criterion = nn.MSELoss()
    optimizer = optim.AdamW(model.parameters(), lr=0.001, weight_decay=1e-4)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='max', factor=0.5, patience=3)
    
    best_val_r2 = -float('inf')
    best_model_weights = None
    
    print("\n--- Training Loop ---")
    epochs = 20
    for epoch in range(1, epochs + 1):
        model.train()
        train_loss = 0.0
        train_preds, train_targets = [], []
        
        for cat_x, cont_x, targets in train_loader:
            cat_x, cont_x, targets = cat_x.to(device), cont_x.to(device), targets.to(device)
            
            optimizer.zero_grad()
            outputs = model(cat_x, cont_x)
            
            loss = criterion(outputs, targets)
            loss.backward()
            optimizer.step()
            
            train_loss += loss.item() * len(targets)
            train_preds.extend(outputs.detach().cpu().numpy())
            train_targets.extend(targets.cpu().numpy())
            
        train_loss /= len(train_dataset)
        train_r2 = r2_score_numpy(np.array(train_targets), np.array(train_preds))
        
        # Validation Loop
        model.eval()
        val_loss = 0.0
        val_preds, val_targets = [], []
        with torch.no_grad():
            for cat_x, cont_x, targets in val_loader:
                cat_x, cont_x, targets = cat_x.to(device), cont_x.to(device), targets.to(device)
                outputs = model(cat_x, cont_x)
                
                loss = criterion(outputs, targets)
                val_loss += loss.item() * len(targets)
                val_preds.extend(outputs.cpu().numpy())
                val_targets.extend(targets.cpu().numpy())
                
        val_loss /= len(val_dataset)
        val_r2 = r2_score_numpy(np.array(val_targets), np.array(val_preds))
        
        print(f"Epoch {epoch:02d}/{epochs} | Train Loss: {train_loss:.6f} R2: {train_r2:.4f} | Val Loss: {val_loss:.6f} R2: {val_r2:.4f}")
        
        scheduler.step(val_r2)
        
        if val_r2 > best_val_r2:
            best_val_r2 = val_r2
            # FIXED: Use copy.deepcopy to prevent shallow copying references that change later
            best_model_weights = copy.deepcopy(model.state_dict())
            print(f"   --> New best validation R2: {best_val_r2:.4f}! Weights saved.")
            
    print(f"\nTraining completed! Best Validation R2: {best_val_r2:.4f}")
    
    # Load actual best weights
    model.load_state_dict(best_model_weights)
    model.eval()
    
    # ----------------- Step 4: Recursive Autoregressive Test Inference -----------------
    print("\n--- Running Recursive Autoregressive Inference on Test Set ---")
    
    # Set up master grid again to have clean states for the loop
    # We will reset grid_df and set MultiIndex
    grid_df = pd.DataFrame(grid_records)
    grid_df.set_index(['geohash', 'day', 'min_of_day'], inplace=True)
    grid_df.loc[train_idx, 'demand'] = train_df['demand'].values
    
    # Group test_df by min_of_day so we can predict step-by-step
    test_times = sorted(test_df['min_of_day'].unique())
    
    # Placeholder for predictions
    test_df['pred_demand'] = 0.0
    
    # Maintain a mapping function for fast time calculations
    # Let's write a helper function to retrieve lags for a specific timestamp
    # since we have MultiIndex, grid_df.loc[(gh, day, min_of_day), 'demand'] is very fast
    # To make it even faster, let's keep grid demand as a dict or a 2D numpy array mapped to indexes
    # Using a nested dictionary {geohash: {day: {min_of_day: demand}}} is incredibly fast in Python!
    print("Building fast grid dictionary for O(1) lookups...")
    grid_dict = {}
    for gh in unique_geos:
        grid_dict[gh] = {48: {}, 49: {}}
        
    # Populate training demands in the dictionary
    for gh, day, mins, dem in zip(train_df['geohash'], train_df['day_orig'], train_df['min_of_day'], train_df['demand']):
        # Map back to original string representation for the dictionary matching the test_df geohashes
        gh_str = label_encoders['geohash'].inverse_transform([gh])[0]
        grid_dict[gh_str][day][mins] = dem
        
    # Helper to get demand
    def get_dem(gh, d, m):
        if m < 0:
            # Shift to previous day
            return grid_dict[gh][d - 1].get(m + 1440, 0.0)
        return grid_dict[gh][d].get(m, 0.0)
        
    non_zero_lags_count = 0
    total_lags_count = 0
    
    for t in test_times:
        print(f"Predicting for timestamp min_of_day: {t} ({t//60:02d}:{t%60:02d})...", end="\r")
        # Extract rows for this timestamp
        test_step_mask = test_df['min_of_day'] == t
        test_step = test_df[test_step_mask].copy()
        
        if len(test_step) == 0:
            continue
            
        # Dynamically calculate lag and rolling features for these geohashes
        step_lags = []
        for gh in test_step['geohash']:
            gh_str = label_encoders['geohash'].inverse_transform([gh])[0]
            
            # Lags
            l15 = get_dem(gh_str, 49, t - 15)
            l30 = get_dem(gh_str, 49, t - 30)
            l45 = get_dem(gh_str, 49, t - 45)
            l1h = get_dem(gh_str, 49, t - 60)
            l2h = get_dem(gh_str, 49, t - 120)
            l24h = get_dem(gh_str, 49, t - 1440) # Day 48 same time
            
            # Rolling (1 hour)
            r_vals = [l15, l30, l45, l1h]
            r_mean = np.mean(r_vals)
            r_max = np.max(r_vals)
            r_std = np.std(r_vals)
            
            step_lags.append([l15, l30, l45, l1h, l2h, l24h, r_mean, r_max, r_std])
            
            if l15 > 0:
                non_zero_lags_count += 1
            total_lags_count += 1
            
        step_lags = np.array(step_lags)
        
        # Assign lags to test_step
        for idx, col in enumerate(fill_cols):
            test_step[col] = step_lags[:, idx]
            
        # Scale continuous features (using same scaler)
        test_step[cont_cols] = scaler.transform(test_step[cont_cols])
        
        # Prepare dataloader
        step_dataset = TrafficDataset(test_step[cat_cols].values, test_step[cont_cols].values)
        step_loader = DataLoader(step_dataset, batch_size=len(test_step), shuffle=False)
        
        # Run inference
        cat_x, cont_x = next(iter(step_loader))
        cat_x, cont_x = cat_x.to(device), cont_x.to(device)
        
        with torch.no_grad():
            preds = model(cat_x, cont_x)
            # Clip predictions to [0.0, 1.0]
            preds = torch.clamp(preds, 0.0, 1.0).cpu().numpy()
            
        # Write predictions back to test_df and grid_dict
        test_df.loc[test_step_mask, 'pred_demand'] = preds
        
        for gh, pred in zip(test_step['geohash'], preds):
            gh_str = label_encoders['geohash'].inverse_transform([gh])[0]
            grid_dict[gh_str][49][t] = pred * 0.9
            
    print(f"\nRecursive inference completed successfully!")
    print(f"Percentage of non-zero lag_15m features in test set: {100 * non_zero_lags_count / total_lags_count:.2f}% (Previously ~2%)")
    
    # Save submission file
    submission_df = pd.DataFrame({
        'Index': test_df['Index'],
        'demand': test_df['pred_demand']
    })
    
    # Verify shape and contents
    print("\n--- Verifying Upgraded Submission ---")
    print(f"Submission shape: {submission_df.shape}")
    print(f"Submission columns: {list(submission_df.columns)}")
    print(f"Nulls in submission: {submission_df.isnull().sum().sum()}")
    
    print("\n--- Compare Distribution Statistics ---")
    print(f"Train demand mean: {train_df['demand'].mean():.4f} | Median: {train_df['demand'].median():.4f} | Max: {train_df['demand'].max():.4f}")
    print(f"Test prediction mean: {submission_df['demand'].mean():.4f} | Median: {submission_df['demand'].median():.4f} | Max: {submission_df['demand'].max():.4f}")
    
    submission_df.to_csv("submission.csv", index=False)
    print("\nSuccessfully saved submission.csv!")

if __name__ == "__main__":
    main()
