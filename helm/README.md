# Helm chart to deploy `docs-preview`

> Original repository is <https://github.com/cscfi/docs-preview>

This chart deploys docs-preview, which will clone a given repository (by default <https://github.com/cscfi/csc-user-guide>),
and build every single branch in the repository. The branches will be available via a web interface. It also offers a API that understands
GitHub hooks and rebuilds the given branch by the hook.

## Parameters

* `values.yaml`:
```yaml
git:
  source: https://github.com/cscfi/docs-preview
  docs: https://github.com/cscfi/csc-user-guide
secret:

host: csc-guide-preview.rahtiapp.fi

replicas: 1
```

|Key|Description|Default|
|:-:|:-:|:-:|
|git.source|The source (including `app.py`) to deploy|https://github.com/cscfi/docs-preview|
|git.docs|The repository hosting the documentation to build|https://github.com/cscfi/csc-user-guide|
|secret|Secret to be used in the web-hook|<empty>|
|host|URL to deploy the public web interface|`csc-guide-review.rahtiapp.fi`|
|replicas|Number of replicas for the Pod|1|

