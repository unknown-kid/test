from minio import Minio
from minio.error import S3Error
from io import BytesIO
from app.config import get_settings

settings = get_settings()

minio_client = Minio(
    settings.MINIO_ENDPOINT,
    access_key=settings.MINIO_ROOT_USER,
    secret_key=settings.MINIO_ROOT_PASSWORD,
    secure=settings.MINIO_USE_SSL,
)


def ensure_bucket():
    if not minio_client.bucket_exists(settings.MINIO_BUCKET):
        minio_client.make_bucket(settings.MINIO_BUCKET)


def upload_pdf(object_key: str, data: bytes, content_type: str = "application/pdf"):
    ensure_bucket()
    minio_client.put_object(
        settings.MINIO_BUCKET,
        object_key,
        BytesIO(data),
        length=len(data),
        content_type=content_type,
    )


def get_pdf(object_key: str) -> bytes:
    response = minio_client.get_object(settings.MINIO_BUCKET, object_key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def delete_pdf(object_key: str):
    try:
        minio_client.remove_object(settings.MINIO_BUCKET, object_key)
    except S3Error:
        raise


def copy_pdf(source_key: str, dest_key: str):
    from minio.commonconfig import CopySource
    ensure_bucket()
    minio_client.copy_object(
        settings.MINIO_BUCKET,
        dest_key,
        CopySource(settings.MINIO_BUCKET, source_key),
    )


def object_exists(object_key: str) -> bool:
    try:
        minio_client.stat_object(settings.MINIO_BUCKET, object_key)
        return True
    except S3Error:
        return False
