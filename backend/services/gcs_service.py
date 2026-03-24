import os
import datetime
from pathlib import Path
from google.cloud import storage
from google.oauth2 import service_account

class GCSService:
    def __init__(self, bucket_name: str, credentials_path: str):
        self.bucket_name = bucket_name
        self.credentials_path = credentials_path
        
        # Load the service account securely from the JSON file
        try:
            self.credentials = service_account.Credentials.from_service_account_file(self.credentials_path)
            self.client = storage.Client(credentials=self.credentials, project=self.credentials.project_id)
            self.bucket = self.client.bucket(self.bucket_name)
            print(f"GCP Storage successfully connected to {self.bucket_name}!")
        except Exception as e:
            print(f"FAILED to authenticate GCP Cloud Storage: {e}")
            self.client = None

    def upload_file(self, local_file_path: Path, gcs_destination_blob_name: str) -> str:
        """Uploads a local file to the bucket and returns the internal GCS object path."""
        if not self.client:
            raise RuntimeError("GCS Client not initialized.")
            
        blob = self.bucket.blob(gcs_destination_blob_name)
        blob.upload_from_filename(str(local_file_path))
        print(f"File {local_file_path.name} securely uploaded to gs://{self.bucket_name}/{gcs_destination_blob_name}.")
        
        return gcs_destination_blob_name

    def generate_signed_url(self, blob_name: str, expiration_minutes: int = 120) -> str:
        """
        Generates a temporary Signed URL that the Next.js frontend can use 
        to securely playback audio and download XMLs without making the bucket fully public.
        """
        if not self.client:
            return ""
            
        blob = self.bucket.blob(blob_name)
        
        url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(minutes=expiration_minutes),
            method="GET",
        )
        return url

    def delete_directory(self, prefix: str):
        """Recursively deletes all objects in the bucket that start with a specific prefix (folder)."""
        if not self.client:
            return
            
        blobs = self.bucket.list_blobs(prefix=prefix)
        for blob in blobs:
            blob.delete()
        print(f"Swept GCP bucket for all files matching prefix: {prefix}")
