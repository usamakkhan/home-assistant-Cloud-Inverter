---
name: Bug report
about: Help me reproduce and fix a Solar Touch problem
title: "[Bug] "
labels: bug
assignees: usama-khursheed
---

## What happened?

Describe the problem and what you expected Solar Touch to do.

## How can I reproduce it?

1. Which source did you choose: **Get Data Locally using Inverter IP** or **CloudInverter.net**?
2. What steps trigger the problem?
3. Does it happen on every update or only sometimes?

## Versions and device

- Home Assistant version:
- Solar Touch version:
- Inverter model and firmware (if known):
- Installation method: HACS or manual

## Sensor details, if relevant

Share the affected entity's **state, unit, device class, and state class** from **Settings → Developer Tools → States**. For Energy dashboard problems, also check **Settings → Developer Tools → Statistics** and tell me the warning shown there. Include the Energy field you are configuring and whether you selected a daily or lifetime counter.

## Logs and screenshots

Paste only the relevant Solar Touch log lines or attach a screenshot showing the problem. For temporary debug logging, add this to `configuration.yaml` and restart Home Assistant:

```yaml
logger:
  logs:
    custom_components.cloud_inverter: debug
```

**Before posting**, remove passwords, API tokens, account identifiers, real serial numbers, MAC addresses, and private IP addresses. Use `ABCDE123456789` as a sample serial. Do not attach unredacted Home Assistant backups or full log files.

## Checks already tried

- [ ] I read the [README](../../README.md) and [installation guide](../../INSTALL.md).
- [ ] I searched existing issues.
- [ ] I restarted Home Assistant or reloaded the integration.
- [ ] I verified the configured inverter source and refresh interval.
