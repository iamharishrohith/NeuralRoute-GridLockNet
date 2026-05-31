import pandas as pd
import numpy as np

def extract_minutes(t_str):
    h, m = map(int, t_str.split(':'))
    return h * 60 + m

def minutes_to_timestamp(mins):
    h = mins // 60
    m = mins % 60
    return f"{h}:{m}"

def main():
    print("--- Loading Preprocessed Datasets ---")
    train_df = pd.read_csv("train_clean.csv")
    test_df = pd.read_csv("test_clean.csv")
    
    # Extract unique geohashes
    unique_geos = list(set(train_df['geohash'].unique()).union(set(test_df['geohash'].unique())))
    print(f"Total unique geohashes in grid: {len(unique_geos)}")
    
    # Create complete timestamps list
    # Day 48: all 96 intervals (0:0 to 23:45)
    day48_mins = [m for m in range(0, 1440, 15)]
    day48_timestamps = [(48, m) for m in day48_mins]
    
    # Day 49: up to 13:45 (0:0 to 13:45 is 56 intervals)
    day49_mins = [m for m in range(0, 840, 15)] # up to 825 inclusive
    day49_timestamps = [(49, m) for m in day49_mins]
    
    all_timestamps = day48_timestamps + day49_timestamps
    print(f"Total timestamps in grid: {len(all_timestamps)}")
    
    # Build the master grid
    print("\n--- Constructing Master Grid ---")
    grid_records = []
    for gh in unique_geos:
        for day, mins in all_timestamps:
            grid_records.append({
                'geohash': gh,
                'day': day,
                'min_of_day': mins,
                'timestamp': minutes_to_timestamp(mins)
            })
            
    grid_df = pd.DataFrame(grid_records)
    
    # Populate the grid with actual demand values from train_clean.csv
    # First, let's parse min_of_day in train_clean
    train_df['min_of_day'] = train_df['timestamp'].apply(extract_minutes)
    
    # Merge train demand into grid
    grid_df = grid_df.merge(train_df[['geohash', 'day', 'min_of_day', 'demand']], 
                            on=['geohash', 'day', 'min_of_day'], how='left')
    
    # Sort grid by geohash and time to make shifting and rolling correct
    grid_df = grid_df.sort_values(by=['geohash', 'day', 'min_of_day']).reset_index(drop=True)
    
    # Compute Lags
    print("\n--- Engineering Lags & Rolling Features ---")
    # Lags (15m, 30m, 45m, 1h, 2h, 24h)
    lag_shifts = {
        'lag_15m': 1,
        'lag_30m': 2,
        'lag_45m': 3,
        'lag_1h': 4,
        'lag_2h': 8,
        'lag_24h': 96
    }
    
    for name, shift in lag_shifts.items():
        grid_df[name] = grid_df.groupby('geohash')['demand'].shift(shift)
        
    # Rolling stats (1-hour window = 4 steps, 2-hour window = 8 steps)
    grid_df['rolling_mean_1h'] = grid_df.groupby('geohash')['demand'].transform(lambda x: x.shift(1).rolling(4, min_periods=1).mean())
    grid_df['rolling_max_1h'] = grid_df.groupby('geohash')['demand'].transform(lambda x: x.shift(1).rolling(4, min_periods=1).max())
    grid_df['rolling_std_1h'] = grid_df.groupby('geohash')['demand'].transform(lambda x: x.shift(1).rolling(4, min_periods=1).std())
    
    # Fill missing lag values with 0.0 (representing empty road / baseline)
    fill_cols = list(lag_shifts.keys()) + ['rolling_mean_1h', 'rolling_max_1h', 'rolling_std_1h']
    grid_df[fill_cols] = grid_df[fill_cols].fillna(0.0)
    
    print("\n--- Mapping Features Back to Datasets ---")
    # Add min_of_day to test_clean
    test_df['min_of_day'] = test_df['timestamp'].apply(extract_minutes)
    
    # Features to merge
    feature_cols = ['geohash', 'day', 'min_of_day'] + fill_cols
    
    # Merge back to train and test
    train_final = train_df.merge(grid_df[feature_cols], on=['geohash', 'day', 'min_of_day'], how='left')
    test_final = test_df.merge(grid_df[feature_cols], on=['geohash', 'day', 'min_of_day'], how='left')
    
    print(f"Final train shape: {train_final.shape}")
    print(f"Final test shape: {test_final.shape}")
    
    # Verify zero NaNs in engineered features
    print("\nMissing values in final train features:")
    print(train_final[fill_cols].isnull().sum())
    print("\nMissing values in final test features:")
    print(test_final[fill_cols].isnull().sum())
    
    # Save final datasets
    train_final.to_csv("train_features.csv", index=False)
    test_final.to_csv("test_features.csv", index=False)
    print("\nSuccessfully saved train_features.csv and test_features.csv!")

if __name__ == "__main__":
    main()
