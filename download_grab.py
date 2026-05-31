import urllib.request
import zipfile
import os

zip_url = "https://s3-ap-southeast-1.amazonaws.com/grab-aiforsea-dataset/traffic-management.zip"
zip_path = "traffic-management.zip"
extract_dir = "grab_data"

print(f"Downloading from {zip_url}...")
try:
    urllib.request.urlretrieve(zip_url, zip_path)
    print("Download complete!")
    
    print("Extracting zip file...")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_dir)
    print("Extraction complete!")
    
    # List files in extracted directory
    print("Files in extracted directory:")
    for root, dirs, files in os.walk(extract_dir):
        for file in files:
            print(os.path.join(root, file))
            
except Exception as e:
    print(f"Error occurred: {e}")
