# APIServer: Presigned URL Download Endpoint

## Summary

Replace the current `StreamingResponse` download endpoint with a **301 redirect to a presigned S3 URL**. This offloads file transfer bandwidth from the API server directly to S3.

## Current Behavior

In `api/files/routes.py`, the download endpoint reads the entire file into memory and streams it back:

```python
# routes.py lines 235-262
@router.get("/download", summary="Download file from S3")
def download_file(
    path: str = Query(...),
    s3_client=Depends(get_s3_client),
) -> StreamingResponse:
    file_content, content_type, filename = services.download_file(
        s3_path=path, s3_client=s3_client
    )
    return StreamingResponse(
        io.BytesIO(file_content),
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
```

The `services.download_file()` function (line 866) calls `s3_client.get_object()` and reads all bytes into memory — problematic for large genomics files.

## Proposed Changes

### 1. Add `generate_presigned_url()` to `api/files/services.py`

```python
def generate_presigned_url(
    s3_path: str,
    s3_client=None,
    expiration: int = 3600,
) -> str:
    """
    Generate a presigned URL for downloading a file from S3.

    Args:
        s3_path: The S3 URI of the file (e.g., s3://bucket/path/file.txt)
        s3_client: Optional boto3 S3 client
        expiration: URL expiration time in seconds (default: 1 hour)

    Returns:
        Presigned URL string

    Raises:
        HTTPException: If S3 path is invalid or credentials unavailable
    """
    if not BOTO3_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="S3 support not available. Install boto3.",
        )

    try:
        bucket, key = _parse_s3_path(s3_path)

        if not key:
            raise ValueError(
                "S3 path must include a file key, not just a bucket"
            )

        if s3_client is None:
            s3_client = boto3.client("s3")

        presigned_url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expiration,
        )
        return presigned_url

    except NoCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AWS credentials not found.",
        ) from exc
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        if error_code == "NoSuchKey":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"File not found: {s3_path}",
            ) from exc
        elif error_code == "NoSuchBucket":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="S3 bucket not found",
            ) from exc
        elif error_code == "AccessDenied":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: {s3_path}",
            ) from exc
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"S3 error: {exc.response['Error']['Message']}",
            ) from exc
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
```

### 2. Update download route in `api/files/routes.py`

Replace the `StreamingResponse` with a `RedirectResponse`:

```python
from fastapi.responses import RedirectResponse  # add import (replace StreamingResponse)

@router.get(
    "/download",
    summary="Download file from S3",
    responses={301: {"description": "Redirect to presigned S3 URL"}},
)
def download_file(
    path: str = Query(
        ...,
        description="S3 URI of file to download (e.g., s3://bucket/path/file.txt)"
    ),
    s3_client=Depends(get_s3_client),
):
    """
    Download a file from S3 via presigned URL redirect.

    Returns a 301 redirect to a time-limited presigned S3 URL.
    The client follows the redirect to download directly from S3,
    offloading bandwidth from the API server.
    """
    presigned_url = services.generate_presigned_url(
        s3_path=path, s3_client=s3_client
    )
    return RedirectResponse(url=presigned_url, status_code=301)
```

### 3. Cleanup

- Remove `import io` from `routes.py` if no longer used elsewhere
- Remove `StreamingResponse` import if no longer used elsewhere
- The existing `services.download_file()` function can be kept for potential future use (e.g., server-side file processing) or removed if not needed

## Client Contract

The NGS360-Downloader client expects:

1. **Request**: `GET /api/v1/files/download?path=s3://bucket/path/file.txt` with `Authorization: Bearer <token>` header
2. **Response**: HTTP 301 with the presigned URL in the response body (as quoted string) or Location header
3. **Follow-up**: Client follows the redirect to download directly from S3

The existing v0 download client already handles 301 redirects by extracting the URL from `response.text` and following it. The v1 client will use the same pattern.

---

## Frontend-UI Compatibility Analysis

> Cross-checked against `../frontend-ui` on 2026-04-14.

### How the frontend currently calls this endpoint

There is exactly **one** consumer of `/api/v1/files/download` in the frontend:

**[`file-browser.tsx`](../frontend-ui/src/components/file-browser.tsx:143)** — the `handleFileDownload` handler:

```typescript
const handleFileDownload = (fileName: string) => {
  const fullPath = currentDirectoryPath.endsWith('/')
    ? `${currentDirectoryPath}${fileName}`
    : `${currentDirectoryPath}/${fileName}`;
  const baseUrl = import.meta.env.VITE_API_URL || '';
  const cleanBaseUrl = baseUrl.endsWith('/') ? baseUrl.slice(0, -1) : baseUrl;
  const url = `${cleanBaseUrl}/api/v1/files/download?path=${encodeURIComponent(fullPath)}`;
  window.open(url, '_blank');
};
```

This uses **`window.open()`** — a full browser navigation, not an XHR/fetch call.

The auto-generated SDK function [`downloadFile()`](../frontend-ui/src/client/sdk.gen.ts:1157) and its TanStack Query wrapper [`downloadFileOptions()`](../frontend-ui/src/client/@tanstack/react-query.gen.ts:2002) exist in the generated client code but are **never imported or called** by any component. They are dead code.

### Compatibility verdict: ✅ Will not break — with one recommended change

| Concern | Status | Detail |
|---------|--------|--------|
| Browser follows redirect | ✅ OK | `window.open()` triggers a top-level navigation. Browsers natively follow 301/302/307 redirects, so the user will seamlessly land on the presigned S3 URL. |
| Authentication | ✅ OK | The current route has no auth dependency (`Depends(get_current_user)` is absent), and `window.open()` sends no `Authorization` header. This behavior is unchanged. |
| CORS | ✅ OK | `window.open()` is a navigation, not a fetch/XHR — CORS does not apply. No S3 CORS configuration is required. |
| Generated SDK (`downloadFile`) | ⚠️ Unused | The SDK function uses `responseType: 'json'` and would break if called against a redirect. However, **no component imports it**, so this is not a runtime risk. It will self-correct when the OpenAPI spec is regenerated. |

### ⚠️ Recommended: Use 307 instead of 301

The plan proposes **HTTP 301 (Moved Permanently)**. For a GET-only endpoint, the redirect-following behavior is **identical** across all common clients:

| Client | 301 | 307 | Difference? |
|--------|-----|-----|-------------|
| `requests.get()` (`allow_redirects=True`, default) | Follows automatically | Follows automatically | None |
| `requests.get()` (`allow_redirects=False`) — e.g. NGS360-Downloader | Returns 301, client reads `response.text` | Returns 307, client reads `response.text` | None (reads body/Location either way) |
| `curl` (no flags) | Shows redirect, does not follow | Shows redirect, does not follow | None |
| `curl -L` | Follows | Follows | None |
| `window.open()` (browser) | Follows | Follows | None |
| **Browser/proxy caching** | **Cached by default** | **Never cached** | **⚠️ This is the difference** |

The 301-vs-307 distinction matters for two things:
1. **Method preservation on POST** (307 preserves POST→POST; 301 may downgrade to GET) — irrelevant here since this is a GET endpoint.
2. **Caching** — 301 is cacheable by default; 307 is not.

Since presigned URLs are **time-limited** (1 hour), a cached 301 redirect would eventually point to an expired URL. This makes 301 dangerous for this use case.

**Use HTTP 307 (Temporary Redirect) instead:**

```python
return RedirectResponse(url=presigned_url, status_code=307)
```

### Summary

No frontend-ui code changes are required. The `window.open()` pattern is inherently redirect-compatible, and `requests.get()` / `curl -L` follow both 301 and 307 identically for GET requests. The only recommended change to the plan is using **307** instead of **301** to prevent browsers and proxies from caching redirects to time-limited presigned URLs.
