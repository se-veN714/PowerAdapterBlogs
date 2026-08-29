"""Production email backends with explicit IPv4 SMTP failover."""

import logging
import smtplib
import socket
from ipaddress import AddressValueError, IPv4Address

from django.conf import settings
from django.core.mail.backends.smtp import DNS_NAME, EmailBackend
from django.core.exceptions import ImproperlyConfigured


logger = logging.getLogger(__name__)


class _IPv4SMTP(smtplib.SMTP):
    def __init__(self, host, port, *, connect_host, **kwargs):
        self._connect_host = connect_host
        super().__init__(host, port, **kwargs)

    def _get_socket(self, host, port, timeout):
        del host
        return socket.create_connection(
            (self._connect_host, port),
            timeout,
            self.source_address,
        )


class _IPv4SMTPSSL(smtplib.SMTP_SSL):
    def __init__(self, host, port, *, connect_host, **kwargs):
        self._connect_host = connect_host
        super().__init__(host, port, **kwargs)

    def _get_socket(self, host, port, timeout):
        del host
        new_socket = socket.create_connection(
            (self._connect_host, port),
            timeout,
            self.source_address,
        )
        return self.context.wrap_socket(new_socket, server_hostname=self._host)


class IPv4FailoverEmailBackend(EmailBackend):
    """Connect to SMTP through IPv4 candidates while preserving TLS SNI."""

    def _configured_fallbacks(self):
        configured = getattr(settings, "EMAIL_SMTP_IPV4_FALLBACKS", ())
        if isinstance(configured, str):
            configured = configured.split(",")
        fallbacks = []
        for value in configured:
            value = str(value).strip()
            if not value:
                continue
            try:
                fallbacks.append(str(IPv4Address(value)))
            except AddressValueError as exc:
                raise ImproperlyConfigured(
                    "EMAIL_SMTP_IPV4_FALLBACKS only accepts IPv4 addresses"
                ) from exc
        return tuple(fallbacks)

    def _candidate_ipv4s(self):
        candidates = []
        try:
            addresses = socket.getaddrinfo(
                self.host,
                self.port,
                family=socket.AF_INET,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror:
            addresses = ()
        for address in addresses:
            if address[0] == socket.AF_INET:
                candidates.append(address[4][0])
        candidates.extend(self._configured_fallbacks())
        return tuple(dict.fromkeys(candidates))

    def _create_connection(self, connect_host):
        connection_params = {
            "connect_host": connect_host,
            "local_hostname": DNS_NAME.get_fqdn(),
        }
        if self.timeout is not None:
            connection_params["timeout"] = self.timeout
        if self.use_ssl:
            connection_params["context"] = self.ssl_context
            connection_class = _IPv4SMTPSSL
        else:
            connection_class = _IPv4SMTP
        return connection_class(self.host, self.port, **connection_params)

    def open(self):
        if self.connection:
            return False

        candidates = self._candidate_ipv4s()
        if not candidates:
            error = OSError("SMTP host has no usable IPv4 candidates")
            if self.fail_silently:
                return None
            raise error

        last_error = None
        for connect_host in candidates:
            connection = None
            try:
                connection = self._create_connection(connect_host)
                if not self.use_ssl and self.use_tls:
                    connection.starttls(context=self.ssl_context)
                if self.username and self.password:
                    connection.login(self.username, self.password)
                self.connection = connection
                return True
            except (
                OSError,
                smtplib.SMTPConnectError,
                smtplib.SMTPServerDisconnected,
            ) as exc:
                last_error = exc
                logger.warning(
                    "SMTP IPv4 candidate unavailable: host=%s candidate=%s error=%s",
                    self.host,
                    connect_host,
                    type(exc).__name__,
                )
                if connection is not None:
                    connection.close()

        if self.fail_silently:
            return None
        raise last_error
