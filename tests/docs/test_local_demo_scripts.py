from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_local_demo_scripts_share_the_backend_proxy_environment_contract() -> None:
    start_script = (ROOT / "scripts" / "start_local_demo.ps1").read_text(encoding="utf-8")
    stop_script = (ROOT / "scripts" / "stop_local_demo.ps1").read_text(encoding="utf-8")
    vite = (ROOT / "web" / "vite.config.ts").read_text(encoding="utf-8")

    assert "UV_LINK_MODE" in start_script and '"copy"' in start_script
    assert "RACS_BACKEND_PORT" in start_script
    assert "VITE_RACS_BACKEND_PORT" in start_script
    assert "@(8000, 8010, 8020, 18000)" in start_script
    assert "Windows-assigned port" in start_script
    assert "Loopback, 0" in start_script
    assert "customer_service.local_server" in start_script
    assert "Get-PnpmLauncher" in start_script
    assert "corepack" in start_script
    assert "packageManifest.packageManager" in start_script
    assert '"^pnpm@\\d+\\.\\d+\\.\\d+$"' in start_script
    assert 'Require-Command "node"' in start_script
    assert ".venv\\Scripts\\python.exe" in start_script
    assert "node_modules\\vite\\bin\\vite.js" in start_script
    assert "Invoke-WebRequest" in start_script
    assert "$frontend.HasExited" in start_script
    assert "Get-NetTCPConnection" in start_script
    assert "OwningProcess" in start_script
    assert "Frontend did not start" in start_script
    assert "Consumer page:" in start_script
    assert ".local-demo-processes.json" in start_script
    assert "Removed stale local demo process record." in start_script
    assert "A local demo process is already running." in start_script
    assert "Local synthetic demo is already running. Opening the consumer page." in start_script
    assert "$existingDemoReady = $true" in start_script
    assert ".local-demo-processes.json" in stop_script
    assert "Stop-VerifiedLocalDemoProcess" in stop_script
    assert "record_version" in start_script
    assert "session_token" in start_script
    assert "local_demo_process_guard.ps1" in start_script
    assert "RACS-local-demo-$sessionToken" in start_script
    assert "VITE_RACS_BACKEND_PORT" in vite


def test_windows_double_click_launchers_delegate_to_the_local_demo_scripts() -> None:
    start_launcher = (ROOT / "scripts" / "启动本地演示.cmd").read_text(encoding="utf-8")
    stop_launcher = (ROOT / "scripts" / "停止本地演示.cmd").read_text(encoding="utf-8")

    assert "start_local_demo.ps1" in start_launcher
    assert "-SkipInstall -OpenBrowser" in start_launcher
    assert "stop_local_demo.ps1" in stop_launcher


def test_pycharm_run_configurations_delegate_to_the_local_demo_entry_point() -> None:
    entry_point = (ROOT / "scripts" / "pycharm_local_demo.py").read_text(encoding="utf-8")
    start_configuration = (ROOT / ".run" / "启动本地演示.run.xml").read_text(encoding="utf-8")
    stop_configuration = (ROOT / ".run" / "停止本地演示.run.xml").read_text(encoding="utf-8")

    assert "start_local_demo.ps1" in entry_point
    assert "stop_local_demo.ps1" in entry_point
    assert "-SkipInstall" in entry_point
    assert "Ready. Consumer page:" in entry_point
    assert 'value="start"' in start_configuration
    assert 'value="stop"' in stop_configuration
