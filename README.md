# LogiTrack

LogiTrack is a premium shipment tracking platform for small delivery businesses.

## Local development

1. Create and activate a virtual environment.
2. Install dependencies:
   ```bash
   python -m pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and adjust values if needed.
4. Run migrations:
   ```bash
   python manage.py migrate
   ```
5. Seed demo data:
   ```bash
   python manage.py seed_demo
   ```
6. Start the app:
   ```bash
   python manage.py runserver
   ```
7. Start a Celery worker in another terminal for background jobs:
   ```bash
   celery -A logitrack worker --loglevel=info
   ```

### Bulk shipment intake

Open **Shipments → Import CSV**, download the provided template, upload the
completed manifest, review row-level validation, and confirm valid rows. Imports
run through Celery and are limited to 5 MB and 5,000 data rows per file. Required
columns are `recipient_name`, `recipient_phone`, `origin`, and `destination`;
optional columns are `customer_reference`, `recipient_email`, `carrier`,
`estimated_delivery`, and `description`. Use ISO date/time values for
`estimated_delivery`. A non-empty
`customer_reference` is unique within the business and serves as the import
idempotency key. Invalid rows are excluded, and transiently failed rows can be
retried from the import results page.

### Recipient delivery choices

Add a recipient email to a shipment or include `recipient_email` in an import.
When dispatch moves that shipment to **Out for Delivery**, LogiTrack queues an
email containing a one-time link to submit drop-off instructions or request a
delivery date within the next 30 days. The link expires after seven days. Date
changes remain requests for dispatch to review; they do not automatically change
the shipment ETA. Submitted preferences appear on the tenant-scoped shipment
detail page. Local development uses the console email backend by default.

For production email, configure `PUBLIC_BASE_URL` to the public HTTPS origin,
`EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`, `EMAIL_HOST`,
`EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, and the appropriate
`EMAIL_USE_TLS` or `EMAIL_USE_SSL`. Configure these in Render for the web service;
the blueprint shares them with the Celery worker. Without SMTP credentials,
delivery invitations cannot reach recipients.

### Media storage

Local development uses `MEDIA_ROOT` when `DEBUG=1` and `USE_S3=0`. Production
requires a private S3-compatible bucket; startup fails if `DEBUG=0` and no bucket
is configured. Set `USE_S3=1`, `AWS_STORAGE_BUCKET_NAME`,
`AWS_ACCESS_KEY_ID`, and `AWS_SECRET_ACCESS_KEY`. For AWS S3, set
`AWS_S3_REGION_NAME` to the bucket's region and leave `AWS_S3_ENDPOINT_URL` empty.
For Cloudflare R2, set `AWS_S3_REGION_NAME=auto` and
`AWS_S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com`.
The Render blueprint passes these settings to the web and Celery worker services;
add the bucket name and credentials in the Render environment before deploying.
Proof-of-delivery objects are private and signed links expire after five minutes.

Login with the demo account:
- Username: `demo`
- Password: `demo12345`

## Deploy to Render

1. Push this repository to GitHub.
2. Create a new Render web service connected to the repo.
3. Render will pick up `render.yaml` and run `build.sh`.
4. Set the required environment variables in the Render dashboard.

## Manual animation verification

Browsers and device sizes checked:
- Chrome desktop, 1440x900
- Chrome mobile emulation, iPhone 12 viewport
- Firefox desktop, 1280x720

## Notes

- Public tracking pages intentionally expose only safe shipment information.
- Status transitions are validated server-side and in the shipment form.
