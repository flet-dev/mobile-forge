import hashlib
import os
from argparse import ArgumentParser

import boto3


def get_sha256(filepath):
    """Calculates the SHA256 hash of a file."""
    with open(filepath, "rb") as f:
        hasher = hashlib.sha256()
        hasher.update(f.read())
        return hasher.hexdigest()


def upload_file(s3_client, bucket_name, local_file_path, remote_file_path):
    """Uploads a file to Cloudflare S2 storage with SHA256 hash in metadata."""
    try:
        with open(local_file_path, "rb") as f:
            sha256_hash = get_sha256(local_file_path)
            metadata = {"sha256": sha256_hash}
            s3_client.upload_fileobj(
                f,
                bucket_name,
                remote_file_path,
                ExtraArgs=dict(Metadata=metadata),
            )
        print(f"Upload successful for {local_file_path}")
    except Exception as e:
        print(f"Error uploading {local_file_path}: {e}")


def main():
    parser = ArgumentParser(
        description="Upload files to Cloudflare S2 storage with SHA256 hash in metadata"
    )
    parser.add_argument(
        "dist_dir",
        help="Path to the directory containing files to upload (absolute or relative)",
    )
    args = parser.parse_args()

    # Get credentials from environment variables
    cf_access_key_id = os.environ.get("CF_ACCESS_KEY_ID")
    cf_secret_access_key = os.environ.get("CF_SECRET_ACCESS_KEY")
    cf_endpoint_url = os.environ.get("CF_ENDPOINT_URL")
    cf_bucket_name = os.environ.get("CF_BUCKET_NAME")

    # Check if required environment variables are set
    if not all(
        [cf_access_key_id, cf_secret_access_key, cf_endpoint_url, cf_bucket_name]
    ):
        print(
            "Error: Missing required environment variables. Please set CF_ACCESS_KEY_ID, CF_SECRET_ACCESS_KEY, CF_ENDPOINT_URL, CF_BUCKET_NAME"
        )
        exit(1)

    # Resolve the provided path to absolute relative to the current directory
    dist_dir = os.path.abspath(args.dist_dir)

    # Check if the directory exists
    if not os.path.isdir(dist_dir):
        print(f"Error: Directory not found: {dist_dir}")
        exit(1)

    # Create S3 client with Cloudflare R2 endpoint
    s3_client = boto3.client(
        "s3",
        endpoint_url=cf_endpoint_url,
        aws_access_key_id=cf_access_key_id,
        aws_secret_access_key=cf_secret_access_key,
    )

    # Loop through files in the directory
    for file in os.listdir(dist_dir):
        local_file_path = os.path.join(dist_dir, file)
        remote_file_path = (
            file  # Upload with the same filename in the bucket (can be modified)
        )
        upload_file(s3_client, cf_bucket_name, local_file_path, remote_file_path)

    print("All files uploaded!")


if __name__ == "__main__":
    main()
