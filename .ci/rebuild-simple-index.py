import os
import re

import boto3

html_header = "<!DOCTYPE html><html><body>\n"
html_root_anchor = '<a href="{0}/">{0}</a></br>\n'
html_package_anchor = '<a href="https://pypi.flet.dev/{key}#sha256={sha256}" data-dist-info-metadata="sha256={sha256}" data-core-metadata="sha256={sha256}">{key}</a></br>\n'
html_footer = "</body></html>\n"


def upload_file(s3_client, bucket_name, local_file_path, remote_file_path):
    """Uploads a file to Cloudflare S2 storage with SHA256 hash in metadata."""
    try:
        with open(local_file_path, "rb") as f:
            s3_client.upload_fileobj(f, bucket_name, remote_file_path)
        print(f"Upload successful for {local_file_path}")
    except Exception as e:
        print(f"Error uploading {local_file_path}: {e}")


def main():
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

    # Create S3 client with Cloudflare R2 endpoint
    s3_client = boto3.client(
        "s3",
        endpoint_url=cf_endpoint_url,
        aws_access_key_id=cf_access_key_id,
        aws_secret_access_key=cf_secret_access_key,
    )

    def normalize(name):
        return re.sub(r"[-_.]+", "-", name).lower()

    index = {}

    for obj in s3_client.list_objects(Bucket=cf_bucket_name)["Contents"]:
        key = obj["Key"]
        if key.endswith("/index.html"):
            parts = key.split("/")
            if len(parts) > 2:
                package_name = parts[1]
            if not package_name in index:
                index[package_name] = []
        elif not key.endswith("index.html"):
            print(key)
            package_name = normalize(key.split("-")[0])
            wheels = index.get(package_name, None)
            if wheels is None:
                wheels = []
                index[package_name] = wheels
            metadata = s3_client.head_object(Bucket=cf_bucket_name, Key=obj["Key"])
            wheels.append({"key": key, "sha256": metadata["Metadata"]["sha256"]})

    print("Writing root index")
    packages = [
        html_root_anchor.format(p)
        for p in sorted([p[0] for p in index.items() if len(p[1]) > 0])
    ]
    lines = [html_header] + packages + [html_footer]
    s3_client.put_object(
        Key="simple/index.html",
        Body="\n".join(lines).encode("utf8"),
        Bucket=cf_bucket_name,
        ContentType="text/html",
    )

    print("Updating package indexes")
    for package_name, files in index.items():
        files.sort(key=lambda f: f["key"])
        versions = [
            html_package_anchor.format(key=f["key"], sha256=f["sha256"]) for f in files
        ]
        key = f"simple/{package_name}/index.html"
        if len(versions) == 0:
            print("Deleting index", key)
            s3_client.delete_object(Key=key, Bucket=cf_bucket_name)
        else:
            print("Updating index", key)
            lines = [html_header] + versions + [html_footer]
            s3_client.put_object(
                Key=key,
                Body="\n".join(lines).encode("utf8"),
                Bucket=cf_bucket_name,
                ContentType="text/html",
            )


if __name__ == "__main__":
    main()
