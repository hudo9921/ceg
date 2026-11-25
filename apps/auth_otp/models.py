from django.db import models
from django.utils import timezone
from datetime import timedelta
import secrets


class WhatsAppOTP(models.Model):
    phone = models.CharField('Telefone / WhatsApp', max_length=30, db_index=True)
    code = models.CharField('Código OTP (6 dígitos)', max_length=6)
    expires_at = models.DateTimeField('Expira em')
    attempts = models.PositiveIntegerField('Tentativas Incorretas', default=0)
    ip_address = models.GenericIPAddressField('IP de Origem', null=True, blank=True)
    is_used = models.BooleanField('Código Utilizado', default=False)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)

    class Meta:
        verbose_name = 'Código OTP WhatsApp'
        verbose_name_plural = 'Códigos OTP WhatsApp'
        ordering = ['-created_at']

    def __str__(self):
        return f"OTP para {self.phone} [{self.code}] - Utilizado: {self.is_used}"

    @classmethod
    def create_for_phone(cls, phone: str, valid_minutes: int = 10, ip_address: str | None = None):
        # Invalida códigos anteriores ainda ativos: apenas um código válido por telefone.
        cls.objects.filter(phone=phone, is_used=False).update(is_used=True)
        code = f"{secrets.randbelow(900000) + 100000}"
        expires_at = timezone.now() + timedelta(minutes=valid_minutes)
        return cls.objects.create(
            phone=phone,
            code=code,
            expires_at=expires_at,
            ip_address=ip_address,
        )

    def is_valid(self) -> bool:
        if self.is_used:
            return False
        if self.attempts >= 5:
            return False
        if timezone.now() > self.expires_at:
            return False
        return True
