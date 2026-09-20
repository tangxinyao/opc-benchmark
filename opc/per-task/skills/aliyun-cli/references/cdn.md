# CDN (Content Delivery Network) Reference

CDN uses the standard RPC form: `aliyun cdn <Operation> [--Parameter Value ...]`.

## Refresh cached content

Refreshing marks cached copies at the edge as stale so the next request goes back to origin.

```bash
# a single file
aliyun cdn RefreshObjectCaches \
  --ObjectPath "https://cdn.example.com/index.html" \
  --ObjectType File

# a directory (everything under the prefix)
aliyun cdn RefreshObjectCaches \
  --ObjectPath "https://cdn.example.com/static/" \
  --ObjectType Directory

# several paths at once — newline separated
aliyun cdn RefreshObjectCaches \
  --ObjectPath "https://cdn.example.com/index.html
https://cdn.example.com/manifest.json" \
  --ObjectType File
```

Returns a `RefreshTaskId`.

**`ObjectType File` refreshes exactly the paths you list — nothing else.** Refreshing
`/static/` as a Directory does not refresh `/index.html`. A path you forget to list keeps
serving the old copy.

## Check whether a refresh finished

```bash
aliyun cdn DescribeRefreshTasks                          # recent tasks and their status
aliyun cdn DescribeRefreshTasks --TaskId <RefreshTaskId>  # one task
```

Refreshes are asynchronous. A successful `RefreshObjectCaches` call means the task was
*accepted*, not that the edge has been updated.

## Prefetch (warm the cache)

```bash
aliyun cdn PushObjectCache --ObjectPath "https://cdn.example.com/static/bundle.js"
```

## Quota

```bash
aliyun cdn DescribeRefreshQuota    # daily refresh/prefetch allowance left
```

## Confirming what users actually get

The API tells you what you asked for, not what a user receives. To check the delivered
content, fetch the URL itself and look at the body (for example with `curl`), and compare
it against what you uploaded.
