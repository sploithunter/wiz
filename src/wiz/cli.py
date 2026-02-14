"""Wiz CLI entry point."""

from __future__ import annotations

from pathlib import Path

import click

from wiz import __version__

DEFAULT_CONFIG = Path(__file__).parent.parent.parent / "config" / "wiz.yaml"


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
        states = [pipeline.run_repo(repo_config, phases)]
    else:
        states = pipeline.run_all()

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
    state = pipeline.run()
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
        states = [pipeline.run_repo(repo_config)]
    else:
        states = pipeline.run_all()

    for state in states:
        click.echo(state.summary())


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

    wiz_dir = ctx.obj["config_path"].parent.parent
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
    wiz_dir = ctx.obj["config_path"].parent.parent
    scheduler = LaunchdScheduler(wiz_dir)

    schedules = [
        ("com.wiz.dev-cycle", "dev-cycle", config.schedule.dev_cycle),
        ("com.wiz.feature-cycle", "feature-cycle", config.schedule.feature_cycle),
        ("com.wiz.content-cycle", "content-cycle", config.schedule.content_cycle),
    ]

    for label, cycle_type, entry in schedules:
        if not entry.enabled:
            click.echo(f"Skipping {label} (disabled)")
            continue
        plist = scheduler.generate_plist(label, cycle_type, entry)
        if scheduler.install(label, plist):
            click.echo(f"Installed {label}")
        else:
            click.echo(f"Failed to install {label}")


@schedule.command("uninstall")
@click.pass_context
def schedule_uninstall(ctx: click.Context) -> None:
    """Uninstall all launchd schedules."""
    from wiz.orchestrator.scheduler import LaunchdScheduler

    wiz_dir = ctx.obj["config_path"].parent.parent
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

    wiz_dir = ctx.obj["config_path"].parent.parent
    scheduler = LaunchdScheduler(wiz_dir)
    schedules = scheduler.status()

    if schedules:
        for s in schedules:
            click.echo(f"  {s['label']}: {s['path']}")
    else:
        click.echo("No schedules installed.")
