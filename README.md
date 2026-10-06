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
