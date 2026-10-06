import io
import qrcode
from PIL import Image

from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.utils import ImageReader
from reportlab.graphics.barcode import createBarcodeDrawing


def generate_thermal_label_pdf(shipment, public_tracking_url: str) -> bytes:
    """
    Generates a standard 4x6-inch (288 x 432 pt) thermal shipping label PDF.
    Contains:
    - Sender & recipient address blocks
    - Human-readable 10-character tracking code
    - Machine-readable Code 128 1D barcode
    - 2D QR code routing to the public tracking URL
    - Delivery PIN verification indicators
    """
    buffer = io.BytesIO()
    
    # Standard 4x6 inch dimensions in points
    width = 4.0 * inch   # 288 pt
    height = 6.0 * inch  # 432 pt
    
    pdf = canvas.Canvas(buffer, pagesize=(width, height))
    pdf.setTitle(f"Shipping-Label-{shipment.tracking_number}")

    # Outer border (thermal cut boundary)
    pdf.setLineWidth(2)
    pdf.rect(10, 10, width - 20, height - 20)

    # 1. Header Section
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(20, height - 32, "LOGITRACK")
    pdf.setFont("Helvetica", 9)
    pdf.drawString(120, height - 30, "ENTERPRISE DISPATCH")

    carrier_name = shipment.carrier or "In-house fleet"
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawRightString(width - 20, height - 30, carrier_name.upper())

    pdf.setLineWidth(1)
    pdf.line(10, height - 42, width - 10, height - 42)

    # 2. Sender / Origin Block
    pdf.setFont("Helvetica-Bold", 7)
    pdf.drawString(20, height - 54, "FROM / ORIGIN:")
    
    business_name = getattr(getattr(shipment, "business", None), "name", "") or "LogiTrack Logistics Center"
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(20, height - 66, business_name[:38])
    pdf.setFont("Helvetica", 8)
    pdf.drawString(20, height - 78, (shipment.origin or "Dispatch Terminal 01")[:42])

    created_str = shipment.created_at.strftime("%Y-%m-%d %H:%M")
    pdf.setFont("Helvetica", 7)
    pdf.drawRightString(width - 20, height - 54, f"SHIP DATE: {created_str}")
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawRightString(width - 20, height - 66, "PRIORITY GROUND")

    pdf.setLineWidth(1)
    pdf.line(10, height - 88, width - 10, height - 88)

    # 3. Recipient Block (Large, prominent)
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(20, height - 102, "SHIP TO:")
    
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(20, height - 120, shipment.recipient_name[:32])

    pdf.setFont("Helvetica", 9)
    pdf.drawString(20, height - 134, f"PHONE: {shipment.recipient_phone}")

    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(20, height - 150, shipment.destination[:36])

    pdf.setLineWidth(1.5)
    pdf.line(10, height - 164, width - 10, height - 164)

    # 4. Tracking Code & ePoD PIN Block
    pdf.setFont("Helvetica", 8)
    pdf.drawString(20, height - 178, "TRACKING NUMBER:")

    pdf.setFont("Helvetica-Bold", 16)
    # Formatted spaced tracking number
    tracking_spaced = " ".join([shipment.tracking_number[i:i+4] for i in range(0, len(shipment.tracking_number), 4)])
    pdf.drawString(20, height - 198, tracking_spaced)

    if shipment.delivery_pin_raw:
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawRightString(width - 20, height - 178, "POD PIN:")
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawRightString(width - 20, height - 198, shipment.delivery_pin_raw)

    pdf.setLineWidth(1)
    pdf.line(10, height - 208, width - 10, height - 208)

    # 5. Machine-readable Code 128 Barcode
    try:
        barcode_drawing = createBarcodeDrawing(
            "Code128",
            value=shipment.tracking_number,
            barWidth=1.5,
            barHeight=48,
            humanReadable=False,
        )
        barcode_drawing.drawOn(pdf, 24, height - 268)
    except Exception:
        # Fallback text representation if barcode engine encounters symbol issue
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawCentredString(width / 2.0, height - 245, f"*{shipment.tracking_number}*")

    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawCentredString(width / 2.0, height - 280, f"LT - {shipment.tracking_number}")

    pdf.setLineWidth(1)
    pdf.line(10, height - 290, width - 10, height - 290)

    # 6. Bottom Grid: 2D QR Code + Digital Routing Specs
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=4,
        border=1,
    )
    qr.add_data(public_tracking_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")

    qr_buffer = io.BytesIO()
    qr_img.save(qr_buffer, format="PNG")
    qr_buffer.seek(0)
    qr_reader = ImageReader(qr_buffer)

    # Draw QR code in bottom-left
    qr_size = 90
    pdf.drawImage(qr_reader, 20, 22, width=qr_size, height=qr_size)

    # Right side meta details
    meta_x = 125
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(meta_x, 102, "SCAN FOR REAL-TIME ePoD")

    pdf.setFont("Helvetica", 7.5)
    pdf.drawString(meta_x, 88, "Digital Handover Portal")
    pdf.drawString(meta_x, 74, f"STATUS: {shipment.get_status_display().upper()}")
    
    est = shipment.estimated_delivery.strftime("%b %d, %Y") if shipment.estimated_delivery else "NOT SPECIFIED"
    pdf.drawString(meta_x, 60, f"EST. DELIVERY: {est}")
    
    pdf.setFont("Helvetica-Oblique", 6.5)
    pdf.drawString(meta_x, 38, "Scan QR via mobile to record recipient signature,")
    pdf.drawString(meta_x, 28, "carrier photo, and GPS handover telemetry.")

    pdf.showPage()
    pdf.save()
    
    buffer.seek(0)
    return buffer.getvalue()

