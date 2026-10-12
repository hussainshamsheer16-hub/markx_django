from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.exceptions import ValidationError
import re

from .models import BulkRequest, Comment, ContactMessage, CustomRequest, Order, Review

TEXT = {"class": ""}


class StyledForm(forms.ModelForm):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        for f in self.fields.values():
            f.widget.attrs.setdefault("placeholder", f.label)


def normalize_pakistani_mobile(value):
    compact = re.sub(r"[\s()-]", "", value or "")
    if re.fullmatch(r"03\d{9}", compact):
        return compact
    if re.fullmatch(r"\+923\d{9}", compact):
        return "0" + compact[3:]
    raise ValidationError("Enter a Pakistani mobile number as 03XXXXXXXXX or +923XXXXXXXXX.")


class PakistaniPhoneFormMixin:
    def clean_phone(self):
        value = self.cleaned_data.get("phone", "")
        if not value and not self.fields["phone"].required:
            return ""
        return normalize_pakistani_mobile(value)


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(
        label="Email address",
        widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email"}),
    )

    def clean(self):
        email = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")
        if email and password:
            users = get_user_model()._default_manager
            matching_staff = list(users.filter(email__iexact=email, is_staff=True)[:2])
            matching_users = matching_staff if len(matching_staff) == 1 else list(users.filter(email__iexact=email)[:2])
            if len(matching_users) == 1:
                self.cleaned_data["username"] = matching_users[0].get_username()
        return super().clean()


class CheckoutForm(PakistaniPhoneFormMixin, StyledForm):
    email = forms.EmailField(required=True, label="Email address")

    class Meta:
        model = Order
        fields = ["full_name", "phone", "email", "address", "city", "notes", "payment_method"]
        widgets = {"address": forms.Textarea(attrs={"rows": 3}), "notes": forms.Textarea(attrs={"rows": 2}), "payment_method": forms.RadioSelect}
        labels = {"full_name": "Full name", "phone": "Phone (03XX XXXXXXX)", "address": "Delivery address", "city": "City", "notes": "Order notes (optional)"}

class CustomForm(PakistaniPhoneFormMixin, StyledForm):
    class Meta:
        model = CustomRequest
        fields = ["name", "phone", "email", "tshirt_type", "color", "size", "quantity", "placement", "custom_text", "custom_text_color", "design_file", "notes"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Name"}),
            "phone": forms.TextInput(attrs={"placeholder": "e.g. 0300 1234567"}),
            "email": forms.EmailInput(attrs={"placeholder": "e.g. ali@example.com"}),
            "tshirt_type": forms.TextInput(attrs={"placeholder": "e.g. Shirt, trousers, or pairs"}),
            "color": forms.TextInput(attrs={"placeholder": "e.g. Black, Navy blue"}),
            "size": forms.TextInput(attrs={"placeholder": "e.g. Medium or 32 waist"}),
            "quantity": forms.NumberInput(attrs={"placeholder": "e.g. 10", "min": "1"}),
            "placement": forms.TextInput(attrs={"placeholder": "e.g. Left chest, sleeve, or back"}),
            "custom_text": forms.Textarea(attrs={"rows": 3, "placeholder": "e.g. Name, team name, or short message"}),
            "custom_text_color": forms.TextInput(attrs={"type": "color"}),
            "design_file": forms.ClearableFileInput(attrs={"title": "Upload a logo or design image"}),
            "notes": forms.Textarea(attrs={"rows": 3, "placeholder": "Add any extra details or instructions"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["color"].label = "Shirt color"

    def clean_color(self):
        color = self.cleaned_data.get("color", "")
        return color.strip()

    def clean_custom_text_color(self):
        color = self.cleaned_data.get("custom_text_color", "")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise forms.ValidationError("Choose a valid text color.")
        return color


class BulkForm(PakistaniPhoneFormMixin, StyledForm):
    class Meta:
        model = BulkRequest
        fields = ["organization", "contact_person", "phone", "email", "order_type", "tshirt_type", "printing_type", "quantity_range", "logo", "notes"]
        widgets = {
            "organization": forms.TextInput(attrs={"placeholder": "e.g. MarkX School or ABC Company"}),
            "contact_person": forms.TextInput(attrs={"placeholder": "e.g. Ali Khan"}),
            "phone": forms.TextInput(attrs={"placeholder": "e.g. 0300 1234567"}),
            "email": forms.EmailInput(attrs={"placeholder": "e.g. ali@example.com"}),
            "order_type": forms.TextInput(attrs={"placeholder": "e.g. Team uniform order"}),
            "tshirt_type": forms.TextInput(attrs={"placeholder": "e.g. Shirts, trousers, or pairs"}),
            "printing_type": forms.TextInput(attrs={"placeholder": "e.g. Logo, names, or numbers"}),
            "quantity_range": forms.TextInput(attrs={"placeholder": "e.g. 50–100 pieces"}),
            "notes": forms.Textarea(attrs={"rows": 3, "placeholder": "e.g. Sizes, colors, and preferred delivery date"}),
        }


class ContactForm(PakistaniPhoneFormMixin, StyledForm):
    class Meta:
        model = ContactMessage
        fields = ["name", "email", "phone", "subject", "message"]
        widgets = {"message": forms.Textarea(attrs={"rows": 5})}


class CommentForm(StyledForm):
    class Meta:
        model = Comment
        fields = ("name", "message")
        labels = {"message": "Your comment"}
        widgets = {"message": forms.Textarea(attrs={"rows": 5, "maxlength": 600})}


class AccountCreationForm(UserCreationForm):
    email = forms.EmailField(required=True, label="Email address")

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Username"
        self.fields["username"].help_text = ""
        self.fields["password1"].label = "Password"
        self.fields["password1"].help_text = "Use at least 8 characters."
        self.fields["password2"].label = "Confirm password"
        for field in self.fields.values():
            field.widget.attrs.setdefault("placeholder", field.label)

class AccountProfileForm(forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ("first_name", "last_name", "email")
        labels = {"first_name": "First name", "last_name": "Last name", "email": "Email address"}

    def __init__(self, *args, **kwargs):
        allow_email = kwargs.pop("allow_email", True)
        super().__init__(*args, **kwargs)
        if not allow_email:
            self.fields.pop("email", None)
        for field in self.fields.values():
            field.widget.attrs.setdefault("placeholder", field.label)


class TrackOrderForm(PakistaniPhoneFormMixin, forms.Form):
    order_number = forms.CharField(max_length=20, label="Order number")
    phone = forms.CharField(max_length=30, label="Phone number", widget=forms.TextInput(attrs={"autocomplete": "tel"}))


class ReviewForm(forms.ModelForm):
    rating = forms.TypedChoiceField(
        choices=[(value, f"{value} / 5") for value in range(1, 6)], coerce=int,
        label="Your rating",
    )

    class Meta:
        model = Review
        fields = ("rating", "comment")
        widgets = {"comment": forms.Textarea(attrs={"rows": 4, "maxlength": 2000})}
