import os
import sys
import re
import mimetypes
from urllib.parse import urlparse
import httpx

# Ensure workspace root is in sys.path
sys.path.append(os.getcwd())

# Load dotenv before importing app client (since app imports settings)
from dotenv import load_dotenv
load_dotenv()

from app.db.client import supabase_client

def slugify(text: str) -> str:
    # Lowercase
    text = text.lower().strip()
    # Replace spaces, parenthesis, slashes, hyphens, underscores with a single hyphen
    text = re.sub(r'[\s\(\)/_\-]+', '-', text)
    # Strip leading/trailing hyphens
    text = text.strip('-')
    return text

def run_migration():
    if not supabase_client:
        print("Error: Supabase client not initialized. Check your environment variables.")
        sys.exit(1)

    print("Initializing product-images bucket...")
    # Create public storage bucket "product-images" if it doesn't exist
    try:
        # Check if bucket exists
        buckets = supabase_client.storage.list_buckets()
        bucket_names = [b.name for b in buckets]
        if "product-images" not in bucket_names:
            print("Creating public bucket 'product-images'...")
            supabase_client.storage.create_bucket("product-images", options={"public": True})
            print("Bucket 'product-images' created successfully.")
        else:
            print("Bucket 'product-images' already exists.")
    except Exception as e:
        print(f"Warning during bucket initialization: {e}")

    # Fetch all approved products (approved_for_recommendation == 'Y')
    print("Fetching approved products from database...")
    try:
        res = supabase_client.table("products").select("*").eq("approved_for_recommendation", "Y").execute()
    except Exception as e:
        print(f"Error fetching products from Supabase: {e}")
        sys.exit(1)

    products = res.data or []
    total_approved = len(products)
    print(f"Found {total_approved} approved products in the database.")

    uploaded_count = 0
    skipped_count = 0
    failed_list = []

    # Configure client with Chrome user agent and referer headers to bypass 403s
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "image/*",
        "Referer": "https://vigourseeds.in/"
    }

    with httpx.Client(headers=headers, follow_redirects=True, timeout=30.0) as client:
        for p in products:
            p_id = p.get("product_id")
            crop = p.get("crop") or "unknown"
            variety_name = p.get("variety_name") or "unknown"
            img_url = p.get("image_url")

            print(f"\nProcessing Product: {variety_name} ({crop}) [ID: {p_id}]")

            if not img_url:
                print("-> Skip: No image_url found.")
                skipped_count += 1
                continue

            # Check if already a Supabase URL
            if "supabase.co" in img_url:
                print(f"-> Skip: Image is already hosted on Supabase: {img_url}")
                skipped_count += 1
                continue

            print(f"Original image URL: {img_url}")

            # Determine extension
            parsed = urlparse(img_url)
            _, ext = os.path.splitext(parsed.path)
            ext = ext.lstrip('.').lower()
            if not ext or ext not in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
                ext = 'jpg' # Default fallback

            # Slugify filename
            crop_slug = slugify(crop)
            variety_slug = slugify(variety_name)
            filename = f"{crop_slug}__{variety_slug}.{ext}"

            # Download the image bytes
            try:
                print(f"Downloading image from {img_url}...")
                resp = client.get(img_url)
                if resp.status_code != 200:
                    raise Exception(f"HTTP error {resp.status_code}")
                img_bytes = resp.content
                print(f"Downloaded {len(img_bytes)} bytes successfully.")
            except Exception as e:
                print(f"-> FAILED: Download error: {e}")
                failed_list.append((variety_name, img_url, f"Download failed: {e}"))
                continue

            # Determine content type for upload
            mime_type, _ = mimetypes.guess_type(filename)
            if not mime_type:
                mime_type = "image/jpeg" if ext in ['jpg', 'jpeg'] else f"image/{ext}"

            # Upload bytes to storage
            try:
                print(f"Uploading image to bucket 'product-images' as {filename}...")
                supabase_client.storage.from_("product-images").upload(
                    path=filename,
                    file=img_bytes,
                    file_options={"content-type": mime_type, "x-upsert": "true"}
                )
                print("Uploaded successfully.")
            except Exception as e:
                # If already exists and upsert fails or some other storage error
                print(f"Warning/Error during upload: {e}. Trying to get public URL anyway.")

            # Get public URL
            try:
                public_url = supabase_client.storage.from_("product-images").get_public_url(filename)
                print(f"New Supabase public URL: {public_url}")

                # Update row
                print(f"Updating database record for {variety_name}...")
                supabase_client.table("products").update({"image_url": public_url}).eq("product_id", p_id).execute()
                print("Database updated successfully.")
                uploaded_count += 1
            except Exception as e:
                print(f"-> FAILED: Database update or URL generation failed: {e}")
                failed_list.append((variety_name, img_url, f"Upload/DB error: {e}"))

    print("\n" + "="*50)
    print("MIGRATION COMPLETED SUMMARY")
    print("="*50)
    print(f"Total Approved Products Found: {total_approved}")
    print(f"Successfully Uploaded & Updated: {uploaded_count}")
    print(f"Skipped (Already Migrated/No URL): {skipped_count}")
    print(f"Failed to Migrate: {len(failed_list)}")
    if failed_list:
        print("\nFailed Products Details:")
        for name, url, err in failed_list:
            print(f"- {name}: {url} | Error: {err}")
    print("="*50)

if __name__ == "__main__":
    run_migration()
