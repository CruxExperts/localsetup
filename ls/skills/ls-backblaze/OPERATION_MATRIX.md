# Backblaze B2 operation matrix (schema version 1)

The closed request schema from `--schema request` is the authoritative nested
field/type/limit contract; `--schema result` defines typed operation results.
The table lists every executable operation and its required (`*`) and optional
fields. Each operation maps to its provider API by the same name, except the
explicit transfer/presigning workflows described below. Unknown fields reject
locally; AWS SDK support alone never expands this allowlist.

Sources: [S3 API overview](https://www.backblaze.com/docs/cloud-storage-s3-compatible-api),
[native API reference](https://www.backblaze.com/apidocs/),
[notifications](https://www.backblaze.com/apidocs/b2-set-bucket-notification-rules),
reviewed 2026-09-08. Native calls use `/b2api/v4/`; account authorization and
notification retrieval use GET, other native calls use POST. Notification GET
uses the `bucketId` query parameter; notification updates send an array.

`R` means at most three total attempts for a safe network read; `W` means one
attempt per mutation, with unknown outcomes requiring read-only reconciliation.
Presigning is local after explicit configuration. SDK retries and region
redirect replay are disabled. Reads within multipart resume use the same bounded
policy; the workflow itself is never replayed.

| Operation / API | Request fields (`*` required) | B2 capability | Execution class |
|---|---|---|---|
| `s3.ListBuckets` | `{}` | listBuckets | R |
| `s3.HeadBucket` | `bucket*` | listBuckets | R |
| `s3.GetBucketLocation` | `bucket*` | listBuckets | R |
| `s3.CreateBucket` | `bucket*`, `object_lock_enabled` | writeBuckets | W |
| `s3.DeleteBucket` | `bucket*` | deleteBuckets | W; destructive; access change |
| `s3.GetBucketAcl` | `bucket*` | listBuckets | R |
| `s3.GetBucketCors` | `bucket*` | listBuckets | R |
| `s3.GetBucketEncryption` | `bucket*` | readBucketEncryption | R |
| `s3.GetBucketLogging` | `bucket*` | readBucketLogging | R |
| `s3.GetBucketVersioning` | `bucket*` | listBuckets | R |
| `s3.PutBucketAcl` | `acl*`, `bucket*` | writeBuckets | W; access change |
| `s3.PutBucketCors` | `bucket*`, `cors_rules*` | writeBuckets | W; access change |
| `s3.DeleteBucketCors` | `bucket*` | writeBuckets | W; access change |
| `s3.PutBucketEncryption` | `bucket*`, `encryption*` | writeBucketEncryption | W; access change |
| `s3.DeleteBucketEncryption` | `bucket*` | writeBucketEncryption | W; access change |
| `s3.PutBucketLogging` | `bucket*`, `logging*` | writeBucketLogging | W; access change |
| `s3.ListObjects` | `bucket*`, `delimiter`, `encoding_type`, `marker`, `max_keys`, `max_pages`, `prefix` | listFiles | R |
| `s3.ListObjectsV2` | `bucket*`, `continuation_token`, `delimiter`, `encoding_type`, `fetch_owner`, `max_keys`, `max_pages`, `prefix`, `start_after` | listFiles | R |
| `s3.ListObjectVersions` | `bucket*`, `delimiter`, `encoding_type`, `key_marker`, `max_keys`, `max_pages`, `prefix`, `version_id_marker` | listFiles | R |
| `s3.HeadObject` | `bucket*`, `encryption`, `key*`, `version_id` | readFiles | R |
| `s3.GetObject` | `bucket*`, `destination*`, `encryption`, `key*`, `overwrite`, `range`, `version_id` | readFiles | R |
| `s3.PutObject` | `bucket*`, `content_encoding`, `content_type`, `encryption`, `key*`, `metadata`, `source*` | writeFiles | W; overwrite |
| `s3.CopyObject` | `bucket*`, `encryption`, `key*`, `metadata`, `metadata_directive`, `source_bucket*`, `source_encryption`, `source_key*`, `source_version_id` | readFiles + writeFiles | W; overwrite |
| `s3.DeleteObject` | `bucket*`, `key*`, `version_id` | deleteFiles | W; destructive |
| `s3.DeleteObjects` | `bucket*`, `objects*`, `quiet` | deleteFiles | W; destructive |
| `s3.GetObjectAcl` | `bucket*`, `key*`, `version_id` | readFiles | R |
| `s3.GetObjectTagging` | `bucket*`, `key*`, `version_id` | readFiles | R |
| `s3.PutObjectAcl` | `acl*`, `bucket*`, `key*`, `version_id` | writeFiles | W; access change |
| `s3.GetObjectLegalHold` | `bucket*`, `key*`, `version_id` | readFileLegalHolds | R |
| `s3.PutObjectLegalHold` | `bucket*`, `key*`, `status*`, `version_id` | writeFileLegalHolds | W; access change |
| `s3.GetObjectRetention` | `bucket*`, `key*`, `version_id` | readFileRetentions | R |
| `s3.PutObjectRetention` | `bucket*`, `bypass_governance`, `key*`, `retention*`, `version_id` | writeFileRetentions | W; access change |
| `s3.GetObjectLockConfiguration` | `bucket*` | readBucketRetentions | R |
| `s3.PutObjectLockConfiguration` | `bucket*`, `configuration*` | writeBucketRetentions | W; access change |
| `s3.CreateMultipartUpload` | `bucket*`, `content_type`, `encryption`, `key*`, `metadata` | writeFiles | W |
| `s3.UploadPart` | `bucket*`, `encryption`, `key*`, `part_number*`, `source*`, `upload_id*` | writeFiles | W |
| `s3.UploadPartCopy` | `bucket*`, `encryption`, `key*`, `part_number*`, `source_bucket*`, `source_encryption`, `source_key*`, `source_range`, `upload_id*` | readFiles + writeFiles | W |
| `s3.ListParts` | `bucket*`, `key*`, `max_parts`, `part_number_marker`, `upload_id*` | listFiles | R |
| `s3.ListMultipartUploads` | `bucket*`, `delimiter`, `key_marker`, `max_uploads`, `prefix`, `upload_id_marker` | listFiles | R |
| `s3.CompleteMultipartUpload` | `bucket*`, `key*`, `parts*`, `upload_id*` | writeFiles | W; overwrite |
| `s3.AbortMultipartUpload` | `bucket*`, `key*`, `upload_id*` | writeFiles | W; destructive |
| `s3.UploadFileMultipart` | `bucket*`, `checkpoint*`, `content_type`, `encryption`, `key*`, `metadata`, `part_size`, `source*` | writeFiles | W; overwrite |
| `s3.ResumeMultipartUpload` | `bucket*`, `checkpoint*`, `encryption`, `key*`, `source*` | writeFiles | W; overwrite |
| `s3.PresignGet` | `bucket*`, `encryption`, `expires_seconds*`, `key*`, `version_id` | readFiles | local signing |
| `s3.PresignPut` | `bucket*`, `content_type`, `encryption`, `expires_seconds*`, `key*` | writeFiles | local signing |
| `native.AuthorizeAccount` | `{}` | selected account key | R |
| `native.ListBuckets` | `bucket_id`, `bucket_name`, `bucket_types` | listBuckets | R |
| `native.CreateBucket` | `bucket_info`, `bucket_name*`, `bucket_type*`, `cors_rules`, `default_server_side_encryption`, `file_lock_enabled`, `lifecycle_rules` | writeBuckets | W; access change |
| `native.UpdateBucket` | `bucket_id*`, `bucket_info`, `bucket_type`, `cors_rules`, `default_retention`, `default_server_side_encryption`, `file_lock_enabled`, `if_revision_is*`, `lifecycle_rules` | writeBuckets | W; access change |
| `native.DeleteBucket` | `bucket_id*` | deleteBuckets | W; destructive; access change |
| `native.ListKeys` | `max_key_count`, `start_application_key_id` | listKeys | R |
| `native.CreateKey` | `bucket_ids`, `capabilities*`, `key_name*`, `name_prefix`, `secret_output*`, `valid_duration_seconds` | writeKeys | W; access change |
| `native.DeleteKey` | `application_key_id*` | deleteKeys | W; destructive |
| `native.GetNotificationRules` | `bucket_id*` | readBucketNotifications | R |
| `native.SetNotificationRules` | `bucket_id*`, `rules*` | writeBucketNotifications | W; access change |

Encryption and lock fields may additionally require `writeBucketEncryption` or
`writeBucketRetentions`; governance bypass requires `bypassGovernance`.
Public access additionally requires `--allow-public`. Native capability checks
use the authorized key’s declared capabilities; the provider remains authoritative
for bucket/name-prefix scope and service permission enforcement.

Each direct operation has closed-request, dispatch, known-rejection, and SDK
serialization coverage in `test_backblaze_matrix.py`,
`test_backblaze_schema_matrix.py`, and `test_backblaze_sdk_serialization.py`.
Native HTTP method/query/token/deadline fixtures are in
`test_backblaze_native_transport.py`. Transfer ambiguity, local no-clobber,
backup, checkpoint and reconciliation coverage is in
`test_backblaze_transfer_recovery.py` and `test_backblaze_protocol.py`.
Secret delivery and endpoint boundaries have independent storage regression tests.
These are offline acceptance tests; live provider qualification is unperformed.

Multipart workflows compose CreateMultipartUpload, UploadPart, ListParts and
CompleteMultipartUpload. Part sizes are 5 MiB–5 GiB with 1 MiB bounded body reads.
PresignGet/PresignPut sign GetObject/PutObject requests and return sensitive URLs.
ListBuckets returns the complete documented list with no AWS pagination fields.
Object-list helpers expose bounded `max_pages`; other lists expose one page and
their provider continuation fields for an explicit subsequent request.

Native bucket names are create-only. Updates require `if_revision_is` and send
only explicitly selected mutable fields. Bucket information, CORS, lifecycle
and notification collections replace their corresponding complete collections.
File lock can only be enabled, never disabled. Default retention affects future
writes. Native disable literals for default encryption/retention remain
unverified and reject; S3 DeleteBucketEncryption is implemented.

Deleting an object name does not erase older versions. A supplied `version_id`
selects permanent version deletion. Object ACLs reflect their bucket ACL; B2
rejects independent object ACL changes. No bucket emptying, purge, or automatic
destructive recovery occurs.

Unsupported: POST presigning, S3 lifecycle/notification APIs (use the native
administration fields), S3 tag writes, tagging/checksum directives ignored by B2,
S3 policies, KMS, website configuration, PutBucketVersioning, and undocumented
request fields. Account signup/billing and duplicate native object transfers are
outside this skill. See SKILL.md for setup, examples, error codes and recovery.
