# Source repositories

The upstream reference repositories are tracked as submodules at specific commits.

| Directory | Repository |
| --- | --- |
| `aisim/` | [NVIDIA AI Simulator](https://github.com/ai-dynamo/aisim) |
| `dynamo/` | [NVIDIA Dynamo](https://github.com/ai-dynamo/dynamo) |

Clone Mirage with the reference repositories:

```sh
git clone --recurse-submodules https://github.com/L1NxFR/Mirage.git
```

For an existing clone:

```sh
git submodule update --init --recursive
```
