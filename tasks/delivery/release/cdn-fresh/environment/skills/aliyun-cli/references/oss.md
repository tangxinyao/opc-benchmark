# OSS (Object Storage Service) Reference

`aliyun oss` embeds ossutil, so object storage is managed through the `aliyun` binary
itself — there is no separate tool to install.

```
aliyun oss <subcommand> [args...] [options...]
```

Credentials, region and endpoint come from the configured profile; you normally do not
pass them per command.

## Upload

```bash
# one file, explicit destination key
aliyun oss cp ./dist/index.html oss://my-bucket/index.html

# overwrite without prompting — flags go AFTER the two paths
aliyun oss cp ./dist/index.html oss://my-bucket/index.html -f
```

Two rules, both easy to get wrong:

- **Flags go after the source and destination.** `aliyun oss cp -f ./dist/index.html
  oss://my-bucket/index.html` does not parse — the destination never reaches ossutil and
  it fails with
  `copy files between local file system is not allowed ... dest_url:./dist/index.html`.
- **Copy one file per call.** The recursive directory form
  (`aliyun oss cp ./dist/ oss://my-bucket/ -r -f`) fails the same way.

`-f` is needed whenever the object already exists, otherwise `cp` waits for a
confirmation that never comes in a non-interactive shell.

`cp` verifies transfers with crc64 by default.

## List

```bash
aliyun oss ls oss://my-bucket/            # objects under a bucket
aliyun oss ls oss://my-bucket/static/     # objects under a prefix
```

## Inspect an object

```bash
aliyun oss stat oss://my-bucket/index.html   # size, ETag, Last-Modified, Content-Type
aliyun oss cat  oss://my-bucket/index.html   # print object content to stdout
```

`stat` is how you confirm *what is actually stored* after an upload — ETag and
Last-Modified tell you whether the object you think you uploaded is the one that is there.

## Local checksum

```bash
aliyun oss hash ./dist/index.html              # crc64 (default)
aliyun oss hash ./dist/index.html --type md5   # md5
```

Compare against the object's ETag/crc64 to prove a file arrived intact.

## Remove

```bash
aliyun oss rm oss://my-bucket/old.js
aliyun oss rm -r oss://my-bucket/static/   # recursive; destructive
```

## Useful options

| Option | Meaning |
|---|---|
| `-r`, `--recursive` | operate on a prefix / directory |
| `-f`, `--force` | do not prompt for confirmation |
| `-u`, `--update` | only upload when newer |
| `-e`, `--endpoint` | override the endpoint |
| `--force-path-style` | path-style addressing instead of virtual-host style |

## Note on caching

Objects served through CDN are cached at the edge. Uploading a new object does **not**
by itself change what users receive — see `references/cdn.md`.
Content-hashed filenames (`bundle.9f2a1c.js`) are new objects and are not affected,
but files whose name stays the same (`index.html`) are.
