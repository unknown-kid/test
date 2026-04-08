import ipaddress
import os
import re
import socket
from email.message import Message
from urllib.parse import unquote, urlparse

import httpx

from app.services.paper_service import MAX_FILE_SIZE

PDF_SIGNATURE = b"%PDF-"
SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _is_pdf_bytes(data: bytes) -> bool:
    return data.startswith(PDF_SIGNATURE)


def _sanitize_filename(name: str | None) -> str:
    raw = (name or "").strip()
    if not raw:
        return "downloaded.pdf"
    basename = os.path.basename(raw)
    sanitized = SAFE_FILENAME_RE.sub("_", basename).strip("._")
    if not sanitized:
        sanitized = "downloaded.pdf"
    if not sanitized.lower().endswith(".pdf"):
        sanitized = f"{sanitized}.pdf"
    return sanitized


def _filename_from_content_disposition(header_value: str | None) -> str | None:
    if not header_value:
        return None
    msg = Message()
    msg["content-disposition"] = header_value
    filename = msg.get_param("filename", header="content-disposition")
    if not filename:
        return None
    return unquote(str(filename).strip("\"'"))


def _reject_private_host(hostname: str) -> None:
    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValueError(f"域名解析失败: {hostname}") from exc

    for info in infos:
        ip_text = info[4][0]
        ip_obj = ipaddress.ip_address(ip_text)
        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_reserved
            or ip_obj.is_unspecified
        ):
            raise ValueError("不允许下载内网或本地地址")


async def download_pdf_from_url(url: str) -> tuple[bytes, str, str]:
    raw_url = (url or "").strip()
    if not raw_url:
        raise ValueError("链接不能为空")

    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("仅支持 http/https 链接")
    if not parsed.hostname:
        raise ValueError("链接缺少有效域名")

    _reject_private_host(parsed.hostname)

    timeout = httpx.Timeout(connect=15.0, read=60.0, write=30.0, pool=30.0)
    headers = {
        "User-Agent": "PaperReadingPlatform/1.0",
        "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.1",
    }

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        try:
            response = await client.get(raw_url, headers=headers)
        except httpx.HTTPError as exc:
            raise ValueError(f"下载失败: {exc}") from exc

        final_url = str(response.url)
        final_parsed = urlparse(final_url)
        if final_parsed.hostname:
            _reject_private_host(final_parsed.hostname)

        if response.status_code >= 400:
            raise ValueError(f"下载失败: 上游返回 {response.status_code}")

        content_length = response.headers.get("content-length")
        if content_length:
            try:
                parsed_length = int(content_length)
            except ValueError:
                parsed_length = None
            if parsed_length is not None and parsed_length > MAX_FILE_SIZE:
                raise ValueError("文件大小不能超过100MB")

        data = response.content
        if len(data) > MAX_FILE_SIZE:
            raise ValueError("文件大小不能超过100MB")
        if not data:
            raise ValueError("下载内容为空")

        content_type = (response.headers.get("content-type") or "").lower()
        if "pdf" not in content_type and not _is_pdf_bytes(data):
            raise ValueError("链接内容不是PDF文件")
        if not _is_pdf_bytes(data):
            raise ValueError("下载内容不是有效的PDF文件")

        filename = (
            _filename_from_content_disposition(response.headers.get("content-disposition"))
            or os.path.basename(unquote(final_parsed.path or ""))
            or "downloaded.pdf"
        )
        return data, _sanitize_filename(filename), final_url
