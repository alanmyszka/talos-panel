import shlex

AIKAR_FLAGS = (
    "-XX:+UseG1GC",
    "-XX:+ParallelRefProcEnabled",
    "-XX:MaxGCPauseMillis=200",
    "-XX:+UnlockExperimentalVMOptions",
    "-XX:+DisableExplicitGC",
    "-XX:+AlwaysPreTouch",
    "-XX:G1NewSizePercent=30",
    "-XX:G1MaxNewSizePercent=40",
    "-XX:G1HeapRegionSize=8M",
    "-XX:G1ReservePercent=20",
    "-XX:G1HeapWastePercent=5",
    "-XX:G1MixedGCCountTarget=4",
    "-XX:InitiatingHeapOccupancyPercent=15",
    "-XX:G1MixedGCLiveThresholdPercent=90",
    "-XX:G1RSetUpdatingPauseTimePercent=5",
    "-XX:SurvivorRatio=32",
    "-XX:+PerfDisableSharedMem",
    "-XX:MaxTenuringThreshold=1",
    "-Dusing.aikars.flags=https://mcflags.emc.gs",
    "-Daikars.new.flags=true",
)

FORBIDDEN_JVM_PREFIXES = (
    "-xms",
    "-xmx",
    "-jar",
    "-cp",
    "-classpath",
    "--class-path",
    "-javaagent",
    "-agentlib",
    "-agentpath",
)


class JvmFlagsError(ValueError):
    pass


def parse_custom_jvm_flags(value: str) -> list[str]:
    if len(value.encode("utf-8")) > 2048:
        raise JvmFlagsError("Custom JVM flags exceed the 2048 byte limit")
    try:
        arguments = shlex.split(value, posix=True)
    except ValueError as exc:
        raise JvmFlagsError("Custom JVM flags contain invalid quoting") from exc
    if len(arguments) > 64:
        raise JvmFlagsError("Custom JVM flags contain too many arguments")
    for argument in arguments:
        lowered = argument.lower()
        if (
            not argument.startswith("-")
            or argument.startswith("@")
            or any(ord(character) < 32 for character in argument)
            or any(lowered.startswith(prefix) for prefix in FORBIDDEN_JVM_PREFIXES)
        ):
            raise JvmFlagsError(f"JVM argument is not allowed: {argument}")
    return arguments


def startup_jvm_arguments(memory_mb: int, use_aikar_flags: bool, custom_flags: str) -> list[str]:
    arguments = [f"-Xms{memory_mb}M", f"-Xmx{memory_mb}M"]
    if use_aikar_flags:
        arguments.extend(AIKAR_FLAGS)
    arguments.extend(parse_custom_jvm_flags(custom_flags))
    return arguments
