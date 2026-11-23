# Swagger UI Authentication Guide

The interactive API docs at `/docs` (`http://localhost:8000/docs` in local development) can send
authenticated requests. Click **Authorize** at the top right of the page. The dialog offers two
schemes; fill in one of them, not both.

| Scheme | Use it when | What you enter |
| --- | --- | --- |
| **HTTPBearer** | You already hold a token: an API key, or a JWT access token | The token |
| **OAuth2PasswordBearer** | You have a local account with a password | Email and password |

Either way, Swagger then sends `Authorization: Bearer <token>` with every request you execute.
The authorization is held by the page, so reloading the page clears it.

## Option 1: Paste a token (HTTPBearer)

This is the only option for accounts that sign in through an OAuth provider (SSO), because those
accounts have no password to type into the other form.

1. Click **Authorize**.
2. Under **HTTPBearer**, paste the token into **Value**. Paste the token alone, without the
   `Bearer ` prefix. Swagger adds the prefix.
3. Click **Authorize**, then **Close**.

Two kinds of token are accepted:

- **JWT access token.** Expires after `ACCESS_TOKEN_EXPIRE_MINUTES` (30 minutes by default).
- **API key** (starts with `ngs360_`). Works until it expires or is retired, so it suits longer
  testing sessions.

### Getting a token

**OAuth provider (SSO) accounts**

- Sign in to the web frontend, open the browser's developer tools, and go to the Network tab.
  Select any request made to the API and copy the value of its `Authorization` request header,
  leaving out the leading `Bearer `.
- Alternatively, drive the OAuth endpoints yourself. `GET /api/v1/auth/oauth/providers` lists the
  configured providers, and opening `/api/v1/auth/oauth/{provider}/authorize` in a browser starts
  the sign-in. The callback endpoint, `GET /api/v1/auth/oauth/{provider}/callback`, returns the
  tokens as JSON. Where the browser ends up after sign-in depends on the redirect URI registered
  with the provider, so when a frontend is deployed, copying the token from it is usually simpler.

**Local accounts**

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=you@example.com&password=YOUR_PASSWORD"

# {
#   "access_token": "eyJ0eXAiOiJKV1Qi...",
#   "refresh_token": "...",
#   "token_type": "bearer",
#   "expires_in": 1800
# }
```

Use the `access_token` value. With a local account you can also skip this and use
[Option 2](#option-2-email-and-password-oauth2passwordbearer).

### Creating an API key

An API key saves you from fetching a new JWT every time one expires. Creating a key requires being
authenticated already, and an active, verified account.

1. Authorize in Swagger with a JWT access token, as above.
2. Execute `POST /api/v1/auth/api-keys` with a body such as:

   ```json
   {
     "name": "Swagger testing",
     "expires_at": null
   }
   ```

3. Copy `key` from the response. It is shown only once.

   ```json
   {
     "id": "...",
     "name": "Swagger testing",
     "key": "ngs360_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
     "key_prefix": "ngs360_XXXXX",
     "expires_at": null,
     "created_at": "2026-05-29T16:52:00.000Z"
   }
   ```

4. Open **Authorize** again, click **Logout** under **HTTPBearer**, and paste the key in place of
   the JWT.

The same request with curl:

```bash
curl -X POST http://localhost:8000/api/v1/auth/api-keys \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Swagger testing", "expires_at": null}'
```

## Option 2: Email and password (OAuth2PasswordBearer)

For local accounts. Swagger posts the form to `POST /api/v1/auth/login` and uses the access token
it gets back.

1. Click **Authorize**.
2. Under **OAuth2PasswordBearer**, enter:
   - **username**: your email address. Login looks the account up by email, so a username does not
     work here.
   - **password**: your account password. A token or API key does not work in this field.
   - **client_id** and **client_secret**: leave empty.
3. Click **Authorize**, then **Close**.

The access token obtained this way expires like any other JWT. When requests start returning 401,
authorize again.

## Checking that it worked

Execute `GET /api/v1/auth/me`. A 200 response with your user profile means requests are being
authenticated.

## Common issues

### 401 "Not authenticated"

No token was sent. You have not authorized yet, or the page was reloaded since you did.

### 401 "Could not validate credentials"

A token was sent but rejected.

- The JWT access token has expired. Get a new one, or switch to an API key.
- The API key has expired or been retired.
- The token was pasted with a `Bearer ` prefix, or with part of it missing.

### 401 "Incorrect email or password"

This comes from the email and password form.

- A token or API key was entered in the password field. Tokens go in the **HTTPBearer** field.
- A username was entered instead of an email address.
- The account signs in through an OAuth provider and has no password. Use
  [Option 1](#option-1-paste-a-token-httpbearer).

### 403 "Email not verified"

Most endpoints require a verified email address. Request a new verification email:

```bash
curl -X POST http://localhost:8000/api/v1/auth/resend-verification \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com"}'
```

### 423 Account locked

After `MAX_FAILED_LOGIN_ATTEMPTS` failed logins (5 by default) the account is locked for
`ACCOUNT_LOCKOUT_DURATION_MINUTES` (30 by default). Wait for the lockout to end, or ask an
administrator to unlock the account.

## Managing API keys

| Request | Effect |
| --- | --- |
| `GET /api/v1/auth/api-keys` | List your keys. The key value itself is never returned again. |
| `POST /api/v1/auth/api-keys/{key_id}/revoke` | Retire a key. It stops authenticating immediately. |
| `DELETE /api/v1/auth/api-keys/{key_id}` | Equivalent to revoke. The record is kept for auditing, not erased. |

Good practice:

- Give keys an `expires_at` and a descriptive name.
- Retire keys you no longer use. Each user may hold at most 25 active keys.
- Treat a key like a password. Do not commit it or paste it into shared documents.

## Additional resources

- [Authentication system](./AUTHENTICATION.md)
- [OAuth2 authorization code flow](./OAuth2_Authorization_Code_Grant_Flow.md)
- [Setup guide](./SETUP.md)
