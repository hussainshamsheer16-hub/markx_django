# MarkX Collection – change log

## Brand
- Palette: black #000000, deep red #601925, white #FFFFFF (static/css/style.css remapped + static/css/markx-brand.css).
- Logos from your Logo variations pack: header/footer/mobile menu use the white horizontal logo; vertical logo on the home story block.
- Favicons (favicon.ico, 16/32 png, apple-touch-icon, 192/512, og-image.jpg) generated from your logo mark. Gloock brand font in static/fonts.

## Home page (templates/store/home.html, store/views.py `home`)
- New sections: category image tiles, promise strip, Shirts / Trousers / Pairs rows, Why MarkX, How it works, brand story.
- Everything has English + Urdu text. Rows use your existing product images.

## Responsive
- Phone / tablet fixes in markx-brand.css; Urdu header + toggle sized for small screens.
- Admin tables become cards on phones (labels filled by static/js/app.js, translated by language.js).

## Receipts
- All receipts PDF: A4, two orders per page (store/views.py `order_receipts_pdf`, reportlab).
- Print all (A4, 2 per page): /dashboard/manage/orders/receipts/print/
- Single order receipt + custom request receipt are A4 half-size.
- Note: the PDF uses Latin-1 fonts, so Urdu characters in an address show as "?" there; the print page shows them correctly.

## Verified
- Stock drops on checkout and is restored when an order is cancelled.
- `manage.py check` passes. 17 older tests in store/tests.py already failed before these changes (outdated expectations).
