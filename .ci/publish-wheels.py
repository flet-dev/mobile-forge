import glob
import hashlib
import os
import zipfile
from argparse import ArgumentParser

import boto3


def get_file_sha256(filepath):
    with open(filepath, "rb") as f:
        return get_content_sha256(f.read())


def get_content_sha256(content):
    hasher = hashlib.sha256()
    hasher.update(content)
    return hasher.hexdigest()


def upload_file(
    s3_client, bucket_name, local_file_path, remote_file_path, wheel_hash, metadata_hash
):
    """Uploads a file to Cloudflare S2 storage with SHA256 hash in metadata."""
    try:
        with open(local_file_path, "rb") as f:
            metadata = {"wheel_hash": wheel_hash, "metadata_hash": metadata_hash}
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
    for file in glob.glob(f"{dist_dir}/*.whl"):
        remote_file_path = os.path.basename(file)

        # extract and upload metadata
        zip = zipfile.ZipFile(file)
        metadata_filename = next(
            filter(lambda f: f.endswith(".dist-info/METADATA"), zip.namelist())
        )
        f = zip.open(metadata_filename)
        content = f.read()
        f.close()
        s3_client.put_object(
            Key=f"{remote_file_path}.metadata",
            Body=content,
            Bucket=cf_bucket_name,
            ContentType="application/octet-stream",
        )

        # upload wheel
        upload_file(
            s3_client,
            cf_bucket_name,
            file,
            remote_file_path,
            wheel_hash=get_file_sha256(file),
            metadata_hash=get_content_sha256(content),
        )

    print("All files uploaded!")


if __name__ == "__main__":
    main()
