import json
import os
from urllib import request, error

from django.conf import settings


class NotificationService:
    """Safe notification wrapper for WhatsApp and other outbound channels."""

    @staticmethod
    def send_whatsapp(phone, message, *, customer_name=""):
        provider = getattr(settings, "MARKX", {}).get("WHATSAPP_PROVIDER", "").strip().lower()
        token = getattr(settings, "MARKX", {}).get("WHATSAPP_TOKEN", "").strip()
        api_url = getattr(settings, "MARKX", {}).get("WHATSAPP_API_URL", "").strip()
        if not (provider and token and api_url):
            return {"ok": False, "provider": provider or "not-configured", "message": "WhatsApp notification is not configured."}

        payload = {"to": phone, "text": message, "customer_name": customer_name}
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            api_url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "MarkX-Store/1.0",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=10) as response:
                body = response.read().decode("utf-8", "ignore")
                return {"ok": response.status < 400, "provider": provider, "response": body}
        except (error.URLError, ValueError, TimeoutError):
            return {"ok": False, "provider": provider, "message": "WhatsApp delivery failed."}

    @staticmethod
    def notify_new_order(order):
        if not order.phone:
            return {"ok": False, "message": "Phone not available."}
        customer_name = order.full_name or "Customer"
        items = order.items.all()
        item_lines = [
            f"- {item.name} (Size: {item.size}, Color: {item.color}) x {item.qty}: PKR {item.price * item.qty:,}"
            for item in items
        ]
        text = "\n".join([
            f"Hi {customer_name}, we received your order.",
            f"Order: {order.number}",
            *item_lines,
            f"Subtotal: PKR {order.subtotal:,}",
            f"Discount: PKR {order.discount:,}",
            f"Delivery: PKR {order.delivery:,}",
            f"Total: PKR {order.total:,}",
            f"Payment: {order.get_payment_method_display()}",
            f"Delivery address: {order.address}, {order.city}",
            "We will keep you updated about your order here.",
        ])
        result = NotificationService.send_whatsapp(order.phone, text, customer_name=customer_name)
        return result

    @staticmethod
    def notify_store_owner(order):
        phone = getattr(settings, "MARKX", {}).get("WHATSAPP_OWNER_PHONE", "").strip()
        if not phone:
            return {"ok": False, "provider": "not-configured", "message": "Store owner WhatsApp is not configured."}
        message = f"New order {order.number}: {order.full_name}, {order.total} PKR."
        return NotificationService.send_whatsapp(phone, message)

    @staticmethod
    def notify_order_status(order, status):
        text = f"Order {order.number} status updated to {status}."
        return NotificationService.send_whatsapp(order.phone, text, customer_name=order.full_name or "Customer")
