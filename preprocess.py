import pandas as pd
import numpy as np
import os

def decode_geohash(geohash):
    base32 = '0123456789bcdefghjkmnpqrstuvwxyz'
    char_map = {char: i for i, char in enumerate(base32)}
    
    lat_interval = (-90.0, 90.0)
    lon_interval = (-180.0, 180.0)
    
    is_even = True
    for char in geohash:
        val = char_map[char]
        for mask in [16, 8, 4, 2, 1]:
            if is_even:
                mid = (lon_interval[0] + lon_interval[1]) / 2
                if val & mask:
                    lon_interval = (mid, lon_interval[1])
                else:
                    lon_interval = (lon_interval[0], mid)
            else:
                mid = (lat_interval[0] + lat_interval[1]) / 2
                if val & mask:
                    lat_interval = (mid, lat_interval[1])
                else:
                    lat_interval = (lat_interval[0], mid)
            is_even = not is_even
            
    lat = (lat_interval[0] + lat_interval[1]) / 2
    lon = (lon_interval[0] + lon_interval[1]) / 2
    return lat, lon

def apply_deterministic_imputation(df):
    df = df.copy()
    
    # 1. Fill LargeVehicles based on RoadType and lanes
    # Highway -> Allowed
    df.loc[(df['RoadType'] == 'Highway'), 'LargeVehicles'] = 'Allowed'
    # Street -> Not Allowed
    df.loc[(df['RoadType'] == 'Street'), 'LargeVehicles'] = 'Not Allowed'
    # Residential 1 or 2 lanes -> Not Allowed
    df.loc[(df['RoadType'] == 'Residential') & (df['NumberofLanes'].isin([1, 2])), 'LargeVehicles'] = 'Not Allowed'
    # Residential 3 lanes -> Allowed
    df.loc[(df['RoadType'] == 'Residential') & (df['NumberofLanes'] == 3), 'LargeVehicles'] = 'Allowed'
    
    # 2. Fill Landmarks based on RoadType and lanes
    # Street -> Yes
    df.loc[(df['RoadType'] == 'Street'), 'Landmarks'] = 'Yes'
    # Residential 1 lane -> No
    df.loc[(df['RoadType'] == 'Residential') & (df['NumberofLanes'] == 1), 'Landmarks'] = 'No'
    # Residential 2 or 3 lanes -> Yes
    df.loc[(df['RoadType'] == 'Residential') & (df['NumberofLanes'].isin([2, 3])), 'Landmarks'] = 'Yes'
    # Highway 2 or 5 lanes -> No
    df.loc[(df['RoadType'] == 'Highway') & (df['NumberofLanes'].isin([2, 5])), 'Landmarks'] = 'No'
    # Highway 3 or 4 lanes -> Yes
    df.loc[(df['RoadType'] == 'Highway') & (df['NumberofLanes'].isin([3, 4])), 'Landmarks'] = 'Yes'

    # 3. Fill missing RoadType based on lanes, large vehicles, and landmarks
    # NumberofLanes 4 or 5 -> Highway
    df.loc[df['RoadType'].isnull() & df['NumberofLanes'].isin([4, 5]), 'RoadType'] = 'Highway'
    
    # NumberofLanes 3 -> Residential (since all 3 lane highways have Allowed/Yes, same as Residential, default to Residential)
    df.loc[df['RoadType'].isnull() & (df['NumberofLanes'] == 3), 'RoadType'] = 'Residential'
    
    # NumberofLanes 2 & LargeVehicles == Allowed -> Highway
    df.loc[df['RoadType'].isnull() & (df['NumberofLanes'] == 2) & (df['LargeVehicles'] == 'Allowed'), 'RoadType'] = 'Highway'
    
    # NumberofLanes 2 & LargeVehicles == Not Allowed -> Residential
    df.loc[df['RoadType'].isnull() & (df['NumberofLanes'] == 2) & (df['LargeVehicles'] == 'Not Allowed'), 'RoadType'] = 'Residential'
    
    # NumberofLanes 1 & Landmarks == No -> Residential
    df.loc[df['RoadType'].isnull() & (df['NumberofLanes'] == 1) & (df['Landmarks'] == 'No'), 'RoadType'] = 'Residential'
    
    # NumberofLanes 1 & Landmarks == Yes -> Street
    df.loc[df['RoadType'].isnull() & (df['NumberofLanes'] == 1) & (df['Landmarks'] == 'Yes'), 'RoadType'] = 'Street'
    
    # Re-apply fills for LargeVehicles and Landmarks after filling RoadType to ensure complete consistency
    df.loc[(df['RoadType'] == 'Highway'), 'LargeVehicles'] = 'Allowed'
    df.loc[(df['RoadType'] == 'Street'), 'LargeVehicles'] = 'Not Allowed'
    df.loc[(df['RoadType'] == 'Residential') & (df['NumberofLanes'].isin([1, 2])), 'LargeVehicles'] = 'Not Allowed'
    df.loc[(df['RoadType'] == 'Residential') & (df['NumberofLanes'] == 3), 'LargeVehicles'] = 'Allowed'
    
    df.loc[(df['RoadType'] == 'Street'), 'Landmarks'] = 'Yes'
    df.loc[(df['RoadType'] == 'Residential') & (df['NumberofLanes'] == 1), 'Landmarks'] = 'No'
    df.loc[(df['RoadType'] == 'Residential') & (df['NumberofLanes'].isin([2, 3])), 'Landmarks'] = 'Yes'
    df.loc[(df['RoadType'] == 'Highway') & (df['NumberofLanes'].isin([2, 5])), 'Landmarks'] = 'No'
    df.loc[(df['RoadType'] == 'Highway') & (df['NumberofLanes'].isin([3, 4])), 'Landmarks'] = 'Yes'
    
    return df

def impute_environmental_features_no_leakage(train_df, test_df):
    train_df = train_df.copy()
    test_df = test_df.copy()
    
    # Calculate statistics STRICTLY on training set
    temp_medians = train_df.groupby('timestamp')['Temperature'].median()
    global_median_temp = train_df['Temperature'].median()
    
    weather_modes = train_df.groupby('timestamp')['Weather'].agg(lambda x: x.mode()[0] if not x.mode().empty else 'Sunny')
    global_mode_weather = train_df['Weather'].mode()[0] if not train_df['Weather'].mode().empty else 'Sunny'
    
    # Apply to train
    train_df['Temperature'] = train_df.apply(
        lambda row: temp_medians[row['timestamp']] if pd.isnull(row['Temperature']) else row['Temperature'], axis=1
    )
    # Apply to test (using train medians)
    test_df['Temperature'] = test_df.apply(
        lambda row: temp_medians.get(row['timestamp'], global_median_temp) if pd.isnull(row['Temperature']) else row['Temperature'], axis=1
    )
    
    # Final backup fills using train global medians
    train_df['Temperature'] = train_df['Temperature'].fillna(global_median_temp)
    test_df['Temperature'] = test_df['Temperature'].fillna(global_median_temp)
    
    # Apply to train
    train_df['Weather'] = train_df.apply(
        lambda row: weather_modes[row['timestamp']] if pd.isnull(row['Weather']) else row['Weather'], axis=1
    )
    # Apply to test (using train modes)
    test_df['Weather'] = test_df.apply(
        lambda row: weather_modes.get(row['timestamp'], global_mode_weather) if pd.isnull(row['Weather']) else row['Weather'], axis=1
    )
    
    # Final backup fills using train global modes
    train_df['Weather'] = train_df['Weather'].fillna(global_mode_weather)
    test_df['Weather'] = test_df['Weather'].fillna(global_mode_weather)
    
    return train_df, test_df

def main():
    print("--- Loading Datasets ---")
    train_df = pd.read_csv("train.csv")
    test_df = pd.read_csv("test.csv")
    
    print("\n--- Running Deterministic Imputation ---")
    train_df = apply_deterministic_imputation(train_df)
    test_df = apply_deterministic_imputation(test_df)
    
    print("\n--- Running Leakage-Free Environmental Imputation ---")
    train_df, test_df = impute_environmental_features_no_leakage(train_df, test_df)
    
    print("\n--- Running Geohash Coordinate Decoding ---")
    # Decode Geohashes to Lat/Lon
    geohash_coords = {}
    unique_geos = set(train_df['geohash'].unique()).union(set(test_df['geohash'].unique()))
    for gh in unique_geos:
        geohash_coords[gh] = decode_geohash(gh)
        
    train_df['latitude'] = train_df['geohash'].map(lambda x: geohash_coords[x][0])
    train_df['longitude'] = train_df['geohash'].map(lambda x: geohash_coords[x][1])
    test_df['latitude'] = test_df['geohash'].map(lambda x: geohash_coords[x][0])
    test_df['longitude'] = test_df['geohash'].map(lambda x: geohash_coords[x][1])
    
    # Extract geohash prefixes (hierarchy)
    for p in [3, 4, 5]:
        train_df[f'geohash_pref{p}'] = train_df['geohash'].str[:p]
        test_df[f'geohash_pref{p}'] = test_df['geohash'].str[:p]
        
    print("\n--- Checking Missing Values After Preprocessing ---")
    print("Train missing:")
    print(train_df.isnull().sum())
    print("Test missing:")
    print(test_df.isnull().sum())
    
    # Save clean datasets
    train_df.to_csv("train_clean.csv", index=False)
    test_df.to_csv("test_clean.csv", index=False)
    print("\nSuccessfully saved train_clean.csv and test_clean.csv (no leakage)!")

if __name__ == "__main__":
    main()
