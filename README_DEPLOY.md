# Deploy MarkX Collections to Railway

## Push to GitHub and create the Railway project

1. Push this project folder to GitHub. Confirm `.env`, `db.sqlite3`, `venv/`, and uploaded `media/` are not committed; `media_seed/` is committed for deployment. The included `.gitignore` excludes these local-only files.
2. Create a Railway project from the GitHub repository. Leave the web service Root Directory empty so Railway builds from the repository root; this repository root already contains `manage.py` and `requirements.txt`. Railway's current new services use dashboard deployment settings; `railway.json` is retained only for existing legacy services.
3. Add a Railway PostgreSQL service. In the web service, set `DATABASE_URL` to the PostgreSQL service's `DATABASE_URL` using Railway's variable reference picker.
4. Add a Volume to the web service mounted at `/data`, and set `MEDIA_ROOT=/data/media`. The start command seeds bundled media after the volume is mounted; user uploads then persist across deployments.
5. Before the first successful production start, set Railway Variables `SECRET_KEY` to a long random secret and `DEBUG=False`. Generate a public domain; the app adds Railway's `RAILWAY_PUBLIC_DOMAIN` to `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`, and allows Railway's health-check hostname. If starting before a Railway domain is assigned, set `ALLOWED_HOSTS` to the assigned hostname. For a custom domain, add its hostname to `ALLOWED_HOSTS` and its `https://` origin to `CSRF_TRUSTED_ORIGINS`.
6. Set `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `RAAST_ACCOUNT_TITLE`, `RAAST_IBAN`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, and `DEFAULT_FROM_EMAIL` as applicable. Payment and email credentials belong in Railway Variables, never in GitHub.
7. Set the Stripe webhook URL to `https://<domain>/payments/stripe/webhook/`.

8. In the web service Settings → Deploy, set Build Command to `python manage.py collectstatic --noinput`, Pre-deploy Command to `python manage.py migrate --noinput && python manage.py add_pairs && python manage.py setup_roles`, Start Command to `python manage.py seed_media && exec gunicorn markx.wsgi --bind 0.0.0.0:$PORT --workers 3 --timeout 60`, and Healthcheck Path to `/health/`. The `Procfile` also contains a startup fallback for services that use it. The pre-deploy command must not seed media because Railway volumes are not mounted in that phase; media seeding belongs in the start command.

Uploaded files are served by Django from the configured volume. For larger deployments, S3 or Cloudinary can replace volume-backed media.

## Create the owner

After deployment, create the owner account:

```bash
railway run python manage.py createsuperuser
```

For a brand-new empty PostgreSQL database, load the bundled starter catalog once:

```bash
railway run python manage.py seed
```

Run this only on an empty database. If you are importing your existing local database below, do not seed first; the import contains your existing products and records.

## Optional SQLite data import

On the machine containing the source SQLite database, export its data:

```bash
python manage.py dumpdata --natural-foreign --natural-primary -e contenttypes -e auth.permission -e sessions -e admin.logentry --indent 2 > data.json
```

After migrations have completed on Railway, import the file:

```bash
railway run python manage.py loaddata data.json
```

Do not upload `db.sqlite3` or `data.json` to GitHub. `media_seed/` restores the bundled product/site images at startup. If the local database refers to additional user-uploaded files from `media/`, copy those files to the Railway volume under the same relative paths as `MEDIA_ROOT` before relying on those records.

The SQLite database remains the default local database when neither Postgres configuration option is set.

## Post-deploy checklist

- Log in to the owner dashboard.
- Place a test order and confirm stock decreases.
- Confirm product and site images load and the favicon loads.
- Create a Manager account and confirm it has no finance or cost access.
- Confirm `/health/` returns `{"status":"ok"}` and Stripe webhooks reach the configured path.
