import csv
import io
import logging
import re
from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from shipments.forms import ShipmentImportRowForm
from shipments.models import Shipment, ShipmentImportBatch, ShipmentImportRow

logger = logging.getLogger(__name__)

REQUIRED_HEADERS = {"recipient_name", "recipient_phone", "origin", "destination"}
ALLOWED_HEADERS = REQUIRED_HEADERS | {
    "customer_reference",
    "recipient_email",
    "carrier",
    "estimated_delivery",
    "description",
}
MAX_IMPORT_ROWS = 5000


def _normalize_header(header):
    return re.sub(r"\s+", "_", (header or "").strip().casefold())


def _discard_source_file(batch):
    if not batch.source_file:
        return
    try:
        batch.source_file.delete(save=False)
    except Exception:
        logger.warning("Could not delete source CSV for shipment import %s", batch.pk, exc_info=True)
        return
    batch.source_file = ""
    batch.save(update_fields=["source_file", "updated_at"])


def validate_shipment_import(batch_id):
    batch = ShipmentImportBatch.objects.select_related("business").get(pk=batch_id)
    if batch.status not in {"queued", "validating"}:
        return batch.status

    batch.status = "validating"
    batch.error_message = ""
    batch.save(update_fields=["status", "error_message", "updated_at"])

    try:
        with batch.source_file.open("rb") as raw_file:
            text_file = io.TextIOWrapper(raw_file, encoding="utf-8-sig", newline="")
            reader = csv.DictReader(text_file, strict=True)
            original_headers = reader.fieldnames
            if not original_headers:
                raise ValueError("The CSV must include a header row.")

            headers = [_normalize_header(header) for header in original_headers]
            if len(headers) != len(set(headers)):
                raise ValueError("The CSV contains duplicate column headers.")

            missing_headers = REQUIRED_HEADERS - set(headers)
            if missing_headers:
                raise ValueError(
                    "Missing required columns: " + ", ".join(sorted(missing_headers))
                )

            unknown_headers = set(headers) - ALLOWED_HEADERS
            if unknown_headers:
                raise ValueError(
                    "Unsupported columns: " + ", ".join(sorted(unknown_headers))
                )

            row_specs = []
            references = set()
            seen_references = set()
            for row_number, raw_row in enumerate(reader, start=2):
                if row_number - 1 > MAX_IMPORT_ROWS:
                    raise ValueError(f"A CSV can contain no more than {MAX_IMPORT_ROWS} data rows.")
                if raw_row is None or not any((value or "").strip() for value in raw_row.values() if value is not None):
                    continue

                errors = []
                if None in raw_row:
                    errors.append("This row has more values than the header row.")
                    values = {}
                else:
                    values = {
                        header: raw_row.get(original_header, "") or ""
                        for original_header, header in zip(original_headers, headers)
                    }

                form = ShipmentImportRowForm(values)
                if not errors and not form.is_valid():
                    errors.extend(
                        f"{field}: {', '.join(messages)}"
                        for field, messages in form.errors.items()
                    )

                payload = {}
                if not errors:
                    payload = dict(form.cleaned_data)
                    eta = payload.get("estimated_delivery")
                    payload["estimated_delivery"] = eta.isoformat() if eta else ""
                    reference = payload.get("customer_reference", "")
                    if reference:
                        if reference in seen_references:
                            errors.append("Customer reference is repeated in this CSV.")
                        else:
                            seen_references.add(reference)
                            references.add(reference)

                row_specs.append(
                    {
                        "import_batch": batch,
                        "row_number": row_number,
                        "payload": payload,
                        "status": "invalid" if errors else "pending",
                        "error_message": "; ".join(errors)[:500],
                    }
                )

        if not row_specs:
            raise ValueError("The CSV contains no shipment rows.")

        existing_references = set(
            Shipment.objects.filter(
                business_id=batch.business_id,
                customer_reference__in=references,
            ).values_list("customer_reference", flat=True)
        )
        for row_spec in row_specs:
            reference = row_spec["payload"].get("customer_reference")
            if row_spec["status"] == "pending" and reference in existing_references:
                row_spec["status"] = "invalid"
                row_spec["error_message"] = "Customer reference already exists in this business."

        valid_count = sum(row["status"] == "pending" for row in row_specs)
        invalid_count = len(row_specs) - valid_count
        with transaction.atomic():
            ShipmentImportRow.objects.bulk_create(
                [ShipmentImportRow(**row_spec) for row_spec in row_specs],
                batch_size=500,
            )
            batch.total_rows = len(row_specs)
            batch.valid_rows = valid_count
            batch.failed_rows = invalid_count
            batch.status = "ready" if valid_count else "completed_with_errors"
            batch.save(
                update_fields=[
                    "total_rows",
                    "valid_rows",
                    "failed_rows",
                    "status",
                    "updated_at",
                ]
            )
        _discard_source_file(batch)
        return batch.status
    except (UnicodeDecodeError, csv.Error, OSError, ValueError, ValidationError) as exc:
        logger.info("Shipment import %s validation failed: %s", batch_id, exc)
        batch.status = "failed"
        batch.error_message = str(exc)[:2000]
        batch.save(update_fields=["status", "error_message", "updated_at"])
        _discard_source_file(batch)
        return batch.status
    except Exception:
        logger.exception("Unexpected validation failure for shipment import %s", batch_id)
        batch.status = "failed"
        batch.error_message = "The CSV could not be validated. Upload it again or contact support."
        batch.save(update_fields=["status", "error_message", "updated_at"])
        _discard_source_file(batch)
        return batch.status


def process_shipment_import(batch_id):
    batch = ShipmentImportBatch.objects.select_related("business", "user").get(pk=batch_id)
    if batch.status not in {"queued", "processing"}:
        return batch.status

    batch.status = "processing"
    batch.error_message = ""
    batch.save(update_fields=["status", "error_message", "updated_at"])

    pending_rows = list(batch.rows.filter(status="pending").values_list("pk", flat=True))
    for row_id in pending_rows:
        try:
            with transaction.atomic():
                row = ShipmentImportRow.objects.select_for_update().get(pk=row_id)
                if row.status != "pending":
                    continue

                payload = dict(row.payload)
                reference = payload.get("customer_reference", "")
                existing = None
                if reference:
                    existing = Shipment.objects.filter(
                        business_id=batch.business_id,
                        customer_reference=reference,
                    ).first()

                if existing:
                    row.shipment = existing
                    row.status = "imported"
                    row.error_message = "Existing shipment reused for this customer reference."
                    row.save(update_fields=["shipment", "status", "error_message"])
                    continue

                eta_value = payload.get("estimated_delivery")
                eta = datetime.fromisoformat(eta_value) if eta_value else None
                shipment = Shipment.objects.create(
                    user=batch.user,
                    business=batch.business,
                    customer_reference=reference,
                    recipient_name=payload["recipient_name"],
                    recipient_phone=payload["recipient_phone"],
                    recipient_email=payload.get("recipient_email", ""),
                    origin=payload["origin"],
                    destination=payload["destination"],
                    carrier=payload.get("carrier") or "In-house fleet",
                    estimated_delivery=eta,
                    description=payload.get("description", ""),
                )
                row.shipment = shipment
                row.status = "imported"
                row.error_message = ""
                row.save(update_fields=["shipment", "status", "error_message"])
        except (IntegrityError, ValidationError, ValueError, TypeError) as exc:
            ShipmentImportRow.objects.filter(pk=row_id, status="pending").update(
                status="failed",
                error_message=str(exc)[:500],
            )
        except Exception as exc:
            logger.exception("Failed to import row %s for batch %s", row_id, batch_id)
            ShipmentImportRow.objects.filter(pk=row_id, status="pending").update(
                status="failed",
                error_message=f"Import failed: {exc}"[:500],
            )

    batch.refresh_from_db()
    batch.imported_rows = batch.rows.filter(status="imported").count()
    batch.failed_rows = batch.rows.filter(status__in=["invalid", "failed"]).count()
    batch.status = "completed" if batch.failed_rows == 0 else "completed_with_errors"
    batch.save(update_fields=["imported_rows", "failed_rows", "status", "updated_at"])
    return batch.status
