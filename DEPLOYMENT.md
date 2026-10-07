# Rastlina admin update

## Prepared changes

Backend repository: https://github.com/rastlina/rastlina_backend
Frontend repository: https://github.com/rastlina/rastlina_frontend

Watch & Shop:
- Upload an MP4 directly from the existing admin.
- Choose the product used by Shop Now.
- Optional thumbnail upload, with linked product image fallback.
- Change order and active status. Up to four videos may be active.
- YouTube URL is hidden and not used by the API/player.
- Upload checks: .mp4 extension, MP4 container header and maximum 20 MB.
- Recommended browser-compatible upload: H.264 MP4, preferably under 5 MB.
- Muted looping playback remains in the existing MP4-only frontend player.

Products:
- Duplicate link in each product list row.
- Duplicate selected products as inactive drafts action.
- Copies prices, content, care, category/brand, space tags, variants/stock,
  delivery estimates and independent image files.
- Generates a new SKU and slug; copies remain inactive.
- Reviews, orders, carts and Watch & Shop associations are not copied.
- Add-product and change-product permissions are required.
- Image storage writes are cleaned up if copying fails.

## Deployment order — backend first

1. Back up the production database and media storage.
2. Merge backend-package contents into the BACKEND repository root.
   Deploy using the backend team's existing production procedure.
3. Run with the existing production environment:
   python manage.py migrate
   python manage.py seed_watch_shop_mp4
4. The import command loads the packaged four MP4s and preview images into
   the configured Django file storage and their matching catalogue products.
   It deactivates unused legacy YouTube cards and does not overwrite records
   that already have an MP4. Run once for this transition, not on every release.
5. Confirm /api/store/watch-and-shop/ returns the four uploaded .mp4 URLs,
   thumbnails and product_slug values.
6. Ensure persistent MEDIA_ROOT/storage survives releases and /media/
   serves MP4s with Content-Type video/mp4, range requests and cache support.
   Configure the proxy's upload size to accept files up to the 20 MB limit.
   No temporary serverless filesystem may be used for persistent uploads.
7. Merge frontend-package contents into the FRONTEND repository root and deploy.
   Do not release the dynamic frontend before the backend migration and seed.
8. Check the homepage shows all four cards and the fourth is Moonshine.
   Check an admin video replacement, thumbnail replacement, order change and
   active switch appear after reloading the homepage.
9. Check each Shop Now opens its selected product.
10. Check duplication creates an inactive copy, images are independent, and
    editing or deleting that draft does not change the source product.

These are deployment acceptance steps for the developer team; application
tests and live deployment have not been performed in this task.
The prepared Python files passed syntax parsing only.

## Admin use after deployment

Watch & Shop:
- Open an existing video.
- Choose an MP4 file, choose the matching product, and optionally a thumbnail.
- Set its order and active status, then Save.
- Reload the website to display the saved content.
- For replacement, edit an existing record; there is no need to add a fifth one.

Products:
- Click Duplicate next to a product, then Create draft copy.
- Update the draft's name, SKU, images, variants, stock and other details.
- Activate and Save once the copy is ready.
- Stock is copied from the source, so review it before activation.

## Current product mapping

1. Rex Begonia -> rex-begonia
2. Calathea Ornata -> calathea-ornata
3. Aglaonema Suksom Jaipong -> aglaonema-suksom-jaipong
4. Philodendron Moonshine -> philodendron-moonshine

The seed assets are the optimized copies of the four videos supplied in this chat.
Audio was removed and progressive-loading metadata moved to the start; video
quality was preserved without re-encoding.

## Scope and limitations

Prepared against the main branches downloaded on 7 October 2026.
The source repositories must correspond to the deployed backend; the current
live API omits product_slug despite the earlier repository serializer having it.
The developer must confirm that the correct backend deployment is being updated.

Legacy URL values stay in the database for compatibility but are hidden from
the admin and excluded from playback. Old historical URLs need not be deleted
to stop using YouTube. The original four static videos remain in frontend public/
for rollback; the new dynamic section reads uploads from the backend.

Status: prepared for developer review and deployment, not live.

