import hashlib
import json
from unittest.mock import patch

from django.test import TestCase, override_settings

from identity_api.auth.session import create_auth_session_token
from identity_api.auth.tokens import decode_auth_token
from identity_api.models import (
    AuthSession,
    Employee,
    WeChatMiniIdentity,
    WeChatMiniRegistrationChallenge,
)
from identity_api.wechat.views import PRIVACY_VERSION


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class WeChatMiniAuthTests(TestCase):
    def login_challenge(self):
        with patch(
            "identity_api.wechat.views.exchange_login_code",
            return_value={"app_id": "wx-test-app", "openid": "openid-1", "unionid": "unionid-1"},
        ):
            response = self.client.post(
                "/api/auth/wechat-mini/login",
                data=json.dumps({"code": "one-time-code"}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def register(self):
        challenge = self.login_challenge()
        response = self.client.post(
            "/api/auth/wechat-mini/register",
            data=json.dumps({
                "registrationToken": challenge["registrationToken"],
                "name": "微信服务人员",
                "privacyAccepted": True,
                "privacyVersion": PRIVACY_VERSION,
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        return challenge, response.json()

    def test_registration_uses_one_time_hashed_challenge_and_mobile_token(self):
        challenge = self.login_challenge()
        raw_token = challenge["registrationToken"]
        record = WeChatMiniRegistrationChallenge.objects.get()
        self.assertNotEqual(record.token_digest, raw_token)
        self.assertEqual(record.token_digest, hashlib.sha256(raw_token.encode("utf-8")).hexdigest())

        missing_consent = self.client.post(
            "/api/auth/wechat-mini/register",
            data=json.dumps({"registrationToken": raw_token, "name": "微信服务人员"}),
            content_type="application/json",
        )
        self.assertEqual(missing_consent.status_code, 400)
        self.assertEqual(missing_consent.json()["code"], "PRIVACY_CONSENT_REQUIRED")

        response = self.client.post(
            "/api/auth/wechat-mini/register",
            data=json.dumps({
                "registrationToken": raw_token,
                "name": "微信服务人员",
                "privacyAccepted": True,
                "privacyVersion": PRIVACY_VERSION,
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        session = response.json()
        claims = decode_auth_token(session["token"])
        self.assertEqual(claims["chn"], "wechat-mini")
        self.assertEqual(claims["aud"], "after-sales-mobile")
        self.assertEqual(session["authChannel"], "wechat-mini")
        employee = Employee.objects.get(user_id=session["user"]["userId"])
        self.assertEqual(employee.identity_source, Employee.IDENTITY_WECHAT_MINI)
        identity = WeChatMiniIdentity.objects.get(employee=employee)
        self.assertEqual(identity.privacy_version, PRIVACY_VERSION)
        self.assertIsNotNone(identity.privacy_agreed_at)

        reused = self.client.post(
            "/api/auth/wechat-mini/register",
            data=json.dumps({
                "registrationToken": raw_token,
                "name": "重复注册",
                "privacyAccepted": True,
                "privacyVersion": PRIVACY_VERSION,
            }),
            content_type="application/json",
        )
        self.assertEqual(reused.status_code, 401)
        self.assertEqual(reused.json()["code"], "WECHAT_REGISTRATION_TOKEN_INVALID")

    def test_native_client_origin_is_allowed_for_login_and_registration(self):
        origin = "http://127.0.0.1:43210"
        with patch(
            "identity_api.wechat.views.exchange_login_code",
            return_value={"app_id": "wx-test-app", "openid": "openid-origin", "unionid": ""},
        ):
            login = self.client.post(
                "/api/auth/wechat-mini/login",
                data=json.dumps({"code": "one-time-code"}),
                content_type="application/json",
                HTTP_ORIGIN=origin,
                HTTP_SEC_FETCH_SITE="cross-site",
            )
        self.assertEqual(login.status_code, 200, login.content)

        registration = self.client.post(
            "/api/auth/wechat-mini/register",
            data=json.dumps({
                "registrationToken": login.json()["registrationToken"],
                "name": "微信服务人员",
                "privacyAccepted": True,
                "privacyVersion": PRIVACY_VERSION,
            }),
            content_type="application/json",
            HTTP_ORIGIN=origin,
            HTTP_SEC_FETCH_SITE="cross-site",
        )
        self.assertEqual(registration.status_code, 201, registration.content)

    def test_native_client_origin_does_not_bypass_management_write_protection(self):
        response = self.client.post(
            "/api/auth/dev/login",
            data="{}",
            content_type="application/json",
            HTTP_ORIGIN="http://127.0.0.1:43210",
            HTTP_SEC_FETCH_SITE="cross-site",
        )

        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json()["code"], "CROSS_ORIGIN_WRITE_BLOCKED")

    def test_wechat_session_refreshes_but_cannot_access_management_directory(self):
        _challenge, session = self.register()
        auth_header = f"Bearer {session['token']}"

        refresh = self.client.post(
            "/api/auth/wechat-mini/refresh",
            content_type="application/json",
            HTTP_AUTHORIZATION=auth_header,
        )
        self.assertEqual(refresh.status_code, 200, refresh.content)
        refreshed_claims = decode_auth_token(refresh.json()["token"])
        self.assertEqual((refreshed_claims["chn"], refreshed_claims["aud"]), ("wechat-mini", "after-sales-mobile"))

        directory = self.client.get("/api/org/employees", HTTP_AUTHORIZATION=auth_header)
        self.assertEqual(directory.status_code, 403)
        self.assertEqual(directory.json()["code"], "AUTH_CHANNEL_FORBIDDEN")

    def test_known_identity_logs_in_without_new_registration_challenge(self):
        _challenge, session = self.register()
        with patch(
            "identity_api.wechat.views.exchange_login_code",
            return_value={"app_id": "wx-test-app", "openid": "openid-1", "unionid": "unionid-updated"},
        ):
            response = self.client.post(
                "/api/auth/wechat-mini/login",
                data=json.dumps({"code": "new-code"}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertNotIn("registrationRequired", response.json())
        self.assertEqual(response.json()["user"]["userId"], session["user"]["userId"])
        self.assertEqual(WeChatMiniIdentity.objects.get().unionid, "unionid-updated")

    def test_account_deletion_unlinks_identity_scrubs_employee_and_revokes_sessions(self):
        _challenge, session = self.register()
        user_id = session["user"]["userId"]
        response = self.client.delete(
            "/api/auth/wechat-mini/account",
            HTTP_AUTHORIZATION=f"Bearer {session['token']}",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(WeChatMiniIdentity.objects.filter(employee_id=user_id).exists())
        employee = Employee.objects.get(user_id=user_id)
        self.assertEqual(employee.name, "已注销微信用户")
        self.assertEqual(employee.status, Employee.STATUS_INACTIVE)
        self.assertEqual(employee.account_status, Employee.ACCOUNT_DISABLED)
        self.assertFalse(AuthSession.objects.filter(user_id=user_id, status=AuthSession.STATUS_ACTIVE).exists())

        stale = self.client.post(
            "/api/auth/wechat-mini/refresh",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {session['token']}",
        )
        self.assertEqual(stale.status_code, 401)

    def test_dingtalk_tokens_keep_platform_channel_for_compatibility(self):
        employee = Employee.objects.create(user_id="ding-user", name="钉钉员工")
        token_payload = create_auth_session_token(employee)
        claims = decode_auth_token(token_payload["token"])
        self.assertEqual((claims["chn"], claims["aud"]), ("dingtalk", "platform"))
