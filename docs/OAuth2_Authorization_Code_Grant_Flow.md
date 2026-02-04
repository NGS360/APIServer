# OAuth 2.0 Authorization Code Grant Flow

## Flow Diagram

```mermaid
sequenceDiagram
    participant User as Resource Owner (User)
    participant Client as Client Application
    participant AuthServer as Authorization Server
    participant ResourceServer as Resource Server

    Note over User,ResourceServer: OAuth 2.0 Authorization Code Grant Flow

    User->>Client: 1. Initiates login/authorization
    
    Client->>AuthServer: 2. Authorization Request<br/>(client_id, redirect_uri, scope, state)
    
    AuthServer->>User: 3. Display login & consent page
    
    User->>AuthServer: 4. Authenticates & grants permission
    
    AuthServer->>Client: 5. Redirect with Authorization Code<br/>(code, state)
    
    Note over Client: Client validates state parameter
    
    Client->>AuthServer: 6. Token Request<br/>(code, client_id, client_secret,<br/>redirect_uri, grant_type)
    
    AuthServer->>AuthServer: 7. Validates authorization code<br/>and client credentials
    
    AuthServer->>Client: 8. Access Token Response<br/>(access_token, token_type,<br/>expires_in, refresh_token)
    
    Client->>ResourceServer: 9. API Request with Access Token<br/>(Authorization: Bearer {access_token})
    
    ResourceServer->>ResourceServer: 10. Validates access token
    
    ResourceServer->>Client: 11. Protected Resource Data
    
    Client->>User: 12. Display requested data
```

## Key Steps Explained

### 1. Authorization Request
Client redirects user to authorization server with parameters including:
- `client_id`: Identifier for the client application
- `redirect_uri`: Where to send the user after authorization
- `scope`: Requested permissions
- `state`: Random string for CSRF protection

### 2. User Authentication
Authorization server authenticates the user and requests consent for the requested permissions.

### 3. Authorization Code Grant
Upon approval, authorization server redirects back to client with an authorization code.

### 4. Token Exchange
Client exchanges the authorization code for an access token by making a back-channel request with client credentials. This request includes:
- `code`: The authorization code received
- `client_id`: Client identifier
- `client_secret`: Client secret (confidential)
- `redirect_uri`: Must match the original request
- `grant_type`: Set to "authorization_code"

### 5. Access Protected Resources
Client uses the access token to make authenticated API requests to the resource server.

## Security Features

- **State parameter**: Prevents CSRF (Cross-Site Request Forgery) attacks by ensuring the response matches the request
- **Authorization code**: Single-use, short-lived code exchanged over back-channel for enhanced security
- **Client authentication**: Client must prove its identity when exchanging code for token
- **Redirect URI validation**: Authorization server validates the redirect URI matches the registered value
- **HTTPS requirement**: All communication should occur over secure HTTPS connections

## Token Response

The access token response typically includes:
- `access_token`: The token used to access protected resources
- `token_type`: Usually "Bearer"
- `expires_in`: Token lifetime in seconds
- `refresh_token`: (Optional) Used to obtain new access tokens without user interaction
- `scope`: The actual scopes granted (may differ from requested)

## Use Cases

This flow is ideal for:
- Web applications with server-side components
- Applications that can securely store client credentials (confidential clients)
- Scenarios requiring the highest level of security

## Best Practices

1. Always use HTTPS for all OAuth communications
2. Implement and validate the `state` parameter
3. Store client secrets securely and never expose them in client-side code
4. Use short-lived authorization codes (typically 10 minutes or less)
5. Implement proper token storage and handling on the client
6. Validate all redirect URIs strictly
7. Consider implementing PKCE (Proof Key for Code Exchange) for additional security
