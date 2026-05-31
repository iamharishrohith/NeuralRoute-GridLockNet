import pandas as pd
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from sklearn.preprocessing import LabelEncoder, StandardScaler
import os

# Set seed for reproducibility
np.random.seed(42)
torch.manual_seed(42)

# Helper function to compute R2 score
def r2_score_pytorch(y_true, y_pred):
    ss_res = torch.sum((y_true - y_pred) ** 2)
    ss_tot = torch.sum((y_true - torch.mean(y_true)) ** 2)
    r2 = 1 - ss_res / (ss_tot + 1e-8)
    return r2.item()

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
        
        # 4. Bounded Output Head
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
        
        # Concatenate spatial, road, and temporal branches
        fused = torch.cat([cat_fusion, cont_features], dim=1)
        
        # Pass through residual blocks
        fused = fused + self.res_block1(fused)
        fused = fused + self.res_block2(fused)
        
        # Output with Sigmoid activation to bound the demand predictions strictly between 0 and 1
        output = torch.sigmoid(self.output_head(fused)).squeeze()
        return output

def main():
    print("--- Loading Preprocessed Features ---")
    train_df = pd.read_csv("train_features.csv")
    test_df = pd.read_csv("test_features.csv")
    
    # Calculate cyclic time features
    for df in [train_df, test_df]:
        df['sin_time'] = np.sin(2 * np.pi * df['min_of_day'] / 1440.0)
        df['cos_time'] = np.cos(2 * np.pi * df['min_of_day'] / 1440.0)
        
    # Define categorical and continuous columns
    cat_cols = ['geohash', 'geohash_pref5', 'geohash_pref4', 'geohash_pref3', 
                'RoadType', 'NumberofLanes', 'LargeVehicles', 'Landmarks', 'Weather']
    
    cont_cols = ['day', 'Temperature', 'sin_time', 'cos_time', 
                 'lag_15m', 'lag_30m', 'lag_45m', 'lag_1h', 'lag_2h', 'lag_24h', 
                 'rolling_mean_1h', 'rolling_max_1h', 'rolling_std_1h']
    
    print("\n--- Encoding Categorical Columns ---")
    # Combine train and test to fit label encoders completely
    combined_df = pd.concat([train_df[cat_cols], test_df[cat_cols]], axis=0, ignore_index=True)
    
    cat_dims = []
    emb_dims = []
    
    # Custom embedding dimensions tailored per category cardinality
    emb_dim_map = {
        'geohash': 64,
        'geohash_pref5': 32,
        'geohash_pref4': 16,
        'geohash_pref3': 8,
        'RoadType': 8,
        'NumberofLanes': 8,
        'LargeVehicles': 4,
        'Landmarks': 4,
        'Weather': 4
    }
    
    for col in cat_cols:
        le = LabelEncoder()
        # Fit on combined
        le.fit(combined_df[col].astype(str))
        train_df[col] = le.transform(train_df[col].astype(str))
        test_df[col] = le.transform(test_df[col].astype(str))
        
        cardinality = len(le.classes_)
        cat_dims.append(cardinality)
        emb_dims.append(emb_dim_map[col])
        print(f"Column '{col}' cardinality: {cardinality} -> Embedding dim: {emb_dim_map[col]}")
        
    print("\n--- Scaling Continuous Columns ---")
    scaler = StandardScaler()
    # Fit scaler on train only to prevent temporal leakage, then transform both
    train_df[cont_cols] = scaler.fit_transform(train_df[cont_cols])
    test_df[cont_cols] = scaler.transform(test_df[cont_cols])
    
    # Custom Out-of-Time validation split
    # Train: Day 48
    # Validation: Day 49 (first 2h 15m)
    val_mask = train_df['day'] > train_df['day'].min() # Since Day 48 is the minimum day
    
    train_split = train_df[~val_mask].copy()
    val_split = train_df[val_mask].copy()
    
    print(f"\n--- Splitting Datasets ---")
    print(f"Train records (Day 48): {train_split.shape[0]}")
    print(f"Validation records (Day 49 early): {val_split.shape[0]}")
    
    # Prepare datasets and loaders
    train_dataset = TrafficDataset(train_split[cat_cols].values, train_split[cont_cols].values, train_split['demand'].values)
    val_dataset = TrafficDataset(val_split[cat_cols].values, val_split[cont_cols].values, val_split['demand'].values)
    test_dataset = TrafficDataset(test_df[cat_cols].values, test_df[cont_cols].values)
    
    train_loader = DataLoader(train_dataset, batch_size=256, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=256, shuffle=False)
    test_loader = DataLoader(test_dataset, batch_size=256, shuffle=False)
    
    # Initialize model
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"\nInitializing GridLockNet on device: {device}")
    model = GridLockNet(cat_dims, emb_dims, len(cont_cols)).to(device)
    
    # Loss and optimizer
    criterion = nn.MSELoss()
    optimizer = optim.AdamW(model.parameters(), lr=0.001, weight_decay=1e-4)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='max', factor=0.5, patience=3, verbose=True)
    
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
        
        # Print metrics
        print(f"Epoch {epoch:02d}/{epochs} | Train Loss: {train_loss:.6f} R2: {train_r2:.4f} | Val Loss: {val_loss:.6f} R2: {val_r2:.4f}")
        
        # Step the scheduler based on validation R2
        scheduler.step(val_r2)
        
        # Save best model
        if val_r2 > best_val_r2:
            best_val_r2 = val_r2
            best_model_weights = model.state_dict().copy()
            print(f"   --> New best validation R2: {best_val_r2:.4f}! Weights saved.")
            
    print(f"\nTraining completed! Best Validation R2: {best_val_r2:.4f}")
    
    # Load best model weights for inference
    model.load_state_dict(best_model_weights)
    model.eval()
    
    print("\n--- Running Inference on Test Set ---")
    test_preds = []
    with torch.no_grad():
        for cat_x, cont_x in test_loader:
            cat_x, cont_x = cat_x.to(device), cont_x.to(device)
            outputs = model(cat_x, cont_x)
            test_preds.extend(outputs.cpu().numpy())
            
    # Clip predictions strictly to [0.0, 1.0] just in case
    test_preds = np.clip(test_preds, 0.0, 1.0)
    
    # Save submission file
    submission_df = pd.DataFrame({
        'Index': test_df['Index'],
        'demand': test_preds
    })
    
    # Verify shape and contents
    print("\n--- Verifying Submission ---")
    print(f"Submission shape: {submission_df.shape}")
    print(f"Submission columns: {list(submission_df.columns)}")
    print(f"Nulls in submission: {submission_df.isnull().sum().sum()}")
    print("Head of submission:")
    print(submission_df.head())
    
    submission_df.to_csv("submission.csv", index=False)
    print("\nSuccessfully saved submission.csv!")

if __name__ == "__main__":
    main()
