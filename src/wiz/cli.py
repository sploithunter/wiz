"""Wiz CLI entry point."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import click

from wiz import __version__

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = Path(__file__).parent.parent.parent / "config" / "wiz.yaml"


def _resolve_wiz_dir(config_path: Path) -> Path:
    """Resolve the wiz repo root from a config path.

    Walks upward from the config's directory looking for scripts/wake.sh.
    Falls back to the config file's parent directory.
    """
    current = config_path.resolve().parent
    for _ in range(10):
        if (current / "scripts" / "wake.sh").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return config_path.resolve().parent


@click.group()
@click.version_option(version=__version__)
@click.option("--config", "-c", type=click.Path(), default=None, help="Config file path")
@click.option("--log-level", default="INFO", help="Log level")
@click.option("--json-logs", is_flag=True, help="JSON log output")
@click.pass_context
def main(
    ctx: click.Context,
    config: str | None,
    log_level: str,
    json_logs: bool,
) -> None:
    """Wiz - Personal AI Agent."""
    from wiz.logging_config import setup_logging

    setup_logging(level=log_level, json_output=json_logs)
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = Path(config) if config else DEFAULT_CONFIG


@main.group()
def run() -> None:
    """Run a cycle."""


@run.command("dev-cycle")
@click.option("--repo", default=None, help="Run only for specific repo")
@click.option("--phase", default=None, help="Run only specific phase")
@click.pass_context
def run_dev_cycle(ctx: click.Context, repo: str | None, phase: str | None) -> None:
    """Run the dev cycle."""
    from wiz.config.loader import load_config
    from wiz.notifications.telegram import TelegramNotifier
    from wiz.orchestrator.pipeline import DevCyclePipeline
    from wiz.orchestrator.reporter import StatusReporter

    config = load_config(ctx.obj["config_path"])
    notifier = TelegramNotifier.from_config(config.telegram)
    pipeline = DevCyclePipeline(config, notifier)

    phases = [phase] if phase else None

    if repo:
        repo_config = next((r for r in config.repos if r.name == repo), None)
        if not repo_config:
            click.echo(f"Repository '{repo}' not found in config")
            return
        repo_names = [repo_config.name]
    else:
        repo_names = [r.name for r in config.repos if r.enabled]

    logger.info("========== Dev cycle starting [repos: %s] ==========", ", ".join(repo_names))
    cycle_start = time.time()

    if repo:
        states = [pipeline.run_repo(repo_config, phases)]
    else:
        states = pipeline.run_all()

    logger.info("========== Dev cycle completed (%.1fs) ==========", time.time() - cycle_start)

    reporter = StatusReporter(notifier)
    summary = reporter.report(states)
    click.echo(summary)


@run.command("content-cycle")
@click.pass_context
def run_content_cycle(ctx: click.Context) -> None:
    """Run the content cycle (blog + social)."""
    from wiz.config.loader import load_config
    from wiz.orchestrator.content_pipeline import ContentCyclePipeline

    config = load_config(ctx.obj["config_path"])
    pipeline = ContentCyclePipeline(config)

    logger.info("========== Content cycle starting ==========")
    cycle_start = time.time()

    state = pipeline.run()

    logger.info("========== Content cycle completed (%.1fs) ==========", time.time() - cycle_start)
    click.echo(state.summary())


@run.command("feature-cycle")
@click.option("--repo", default=None, help="Run only for specific repo")
@click.pass_context
def run_feature_cycle(ctx: click.Context, repo: str | None) -> None:
    """Run the feature cycle (propose or implement features)."""
    from wiz.config.loader import load_config
    from wiz.orchestrator.feature_pipeline import FeatureCyclePipeline

    config = load_config(ctx.obj["config_path"])
    pipeline = FeatureCyclePipeline(config)

    if repo:
        repo_config = next((r for r in config.repos if r.name == repo), None)
        if not repo_config:
            click.echo(f"Repository '{repo}' not found in config")
            return
        repo_names = [repo_config.name]
    else:
        repo_names = [r.name for r in config.repos if r.enabled]

    logger.info("========== Feature cycle starting [repos: %s] ==========", ", ".join(repo_names))
    cycle_start = time.time()

    if repo:
        states = [pipeline.run_repo(repo_config)]
    else:
        states = pipeline.run_all()

    logger.info("========== Feature cycle completed (%.1fs) ==========", time.time() - cycle_start)

    for state in states:
        click.echo(state.summary())


@main.command("google-auth")
@click.pass_context
def google_auth(ctx: click.Context) -> None:
    """Authorize Google Docs access (one-time browser flow)."""
    from wiz.config.loader import load_config
    from wiz.integrations.google_docs import GoogleDocsClient

    config = load_config(ctx.obj["config_path"])
    if GoogleDocsClient.authorize(config.google_docs):
        click.echo("Google Docs authorization successful.")
    else:
        click.echo("Google Docs authorization failed. Check credentials file path.")


@main.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show current Wiz status."""
    from wiz.config.loader import load_config
    from wiz.orchestrator.scheduler import LaunchdScheduler

    config = load_config(ctx.obj["config_path"])

    click.echo(f"Wiz v{__version__}")
    click.echo(f"Config: {ctx.obj['config_path']}")
    click.echo(f"Bridge: {config.global_.coding_agent_bridge_url}")
    click.echo(f"\nRepositories ({len(config.repos)}):")
    for r in config.repos:
        status_str = "enabled" if r.enabled else "disabled"
        self_str = " (self-improve)" if r.self_improve else ""
        click.echo(f"  {r.name}: {status_str}{self_str}")

    wiz_dir = _resolve_wiz_dir(ctx.obj["config_path"])
    scheduler = LaunchdScheduler(wiz_dir)
    schedules = scheduler.status()
    if schedules:
        click.echo(f"\nSchedules ({len(schedules)}):")
        for s in schedules:
            click.echo(f"  {s['label']}")
    else:
        click.echo("\nNo schedules installed.")


@main.group()
def schedule() -> None:
    """Manage launchd schedules."""


@schedule.command("install")
@click.pass_context
def schedule_install(ctx: click.Context) -> None:
    """Install launchd schedules from config."""
    from wiz.config.loader import load_config
    from wiz.orchestrator.scheduler import LaunchdScheduler

    config = load_config(ctx.obj["config_path"])
    wiz_dir = _resolve_wiz_dir(ctx.obj["config_path"])
    scheduler = LaunchdScheduler(wiz_dir)

    # Per-phase schedules override the combined dev_cycle if present
    phase_schedules = [
        ("com.wiz.bug-hunt", "dev-cycle", config.schedule.bug_hunt, ["--phase", "bug_hunt"]),
        ("com.wiz.bug-fix", "dev-cycle", config.schedule.bug_fix, ["--phase", "bug_fix"]),
        ("com.wiz.review", "dev-cycle", config.schedule.review, ["--phase", "review"]),
    ]
    has_phase_schedules = any(entry is not None for _, _, entry, _ in phase_schedules)

    if has_phase_schedules:
        # Use per-phase scheduling (staggered)
        schedules = [(l, c, e, a) for l, c, e, a in phase_schedules if e is not None]
    else:
        # Fall back to combined dev_cycle
        schedules = [
            ("com.wiz.dev-cycle", "dev-cycle", config.schedule.dev_cycle, []),
        ]

    # Always add feature and content cycles
    schedules.extend([
        ("com.wiz.feature-cycle", "feature-cycle", config.schedule.feature_cycle, []),
        ("com.wiz.content-cycle", "content-cycle", config.schedule.content_cycle, []),
    ])

    for label, cycle_type, entry, extra_args in schedules:
        if not entry.enabled:
            click.echo(f"Skipping {label} (disabled)")
            continue
        plist = scheduler.generate_plist(label, cycle_type, entry, extra_args or None)
        if scheduler.install(label, plist):
            click.echo(f"Installed {label}")
        else:
            click.echo(f"Failed to install {label}")


@schedule.command("uninstall")
@click.pass_context
def schedule_uninstall(ctx: click.Context) -> None:
    """Uninstall all launchd schedules."""
    from wiz.orchestrator.scheduler import LaunchdScheduler

    wiz_dir = _resolve_wiz_dir(ctx.obj["config_path"])
    scheduler = LaunchdScheduler(wiz_dir)

    for s in scheduler.status():
        if scheduler.uninstall(s["label"]):
            click.echo(f"Uninstalled {s['label']}")
        else:
            click.echo(f"Failed to uninstall {s['label']}")


@schedule.command("status")
@click.pass_context
def schedule_status(ctx: click.Context) -> None:
    """Show installed schedules."""
    from wiz.orchestrator.scheduler import LaunchdScheduler

    wiz_dir = _resolve_wiz_dir(ctx.obj["config_path"])
    scheduler = LaunchdScheduler(wiz_dir)
    schedules = scheduler.status()

    if schedules:
        for s in schedules:
            click.echo(f"  {s['label']}: {s['path']}")
    else:
        click.echo("No schedules installed.")
