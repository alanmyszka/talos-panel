import stat

from talos_panel.config import Settings


def security_findings(settings: Settings, runtime) -> list[dict[str, str]]:
    findings = []
    if not settings.secure_cookies:
        findings.append(
            {
                "severity": "warning",
                "title": "HTTPS cookies are disabled",
                "detail": "Enable SECURE_COOKIES when the panel is served through HTTPS.",
            }
        )
    if "change-me" in settings.database_url:
        findings.append(
            {
                "severity": "critical",
                "title": "Default database password",
                "detail": "Replace the default PostgreSQL password before exposing the panel.",
            }
        )
    try:
        mode = settings.secret_file.stat().st_mode
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            findings.append(
                {
                    "severity": "warning",
                    "title": "Application secret permissions are broad",
                    "detail": "The secret file should be readable only by the panel process.",
                }
            )
    except OSError:
        findings.append(
            {
                "severity": "critical",
                "title": "Application secret is unavailable",
                "detail": "Talos could not inspect its persistent application secret.",
            }
        )
    findings.append(
        {
            "severity": "info",
            "title": "Docker socket grants host-level control",
            "detail": "Only trusted administrators should access Talos; keep the panel bound to localhost or behind an authenticated HTTPS proxy.",
        }
    )
    try:
        containers = runtime.client.containers.list(
            all=True, filters={"label": "io.talos-panel.managed=true"}
        )
        for container in containers:
            container.reload()
            host_config = container.attrs.get("HostConfig", {})
            if host_config.get("Privileged"):
                findings.append(
                    {
                        "severity": "critical",
                        "title": "Privileged Minecraft container",
                        "detail": f"Container {container.name} must not run in privileged mode.",
                    }
                )
            if host_config.get("NetworkMode") == "host":
                findings.append(
                    {
                        "severity": "warning",
                        "title": "Minecraft container uses host networking",
                        "detail": f"Container {container.name} bypasses Docker network isolation.",
                    }
                )
            if not host_config.get("Memory"):
                findings.append(
                    {
                        "severity": "warning",
                        "title": "Minecraft container has no memory limit",
                        "detail": f"Container {container.name} can exhaust host memory.",
                    }
                )
    except Exception as exc:
        findings.append(
            {
                "severity": "warning",
                "title": "Docker security check failed",
                "detail": str(exc)[:240],
            }
        )
    return findings
