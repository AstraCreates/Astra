#!/usr/bin/env python3
import hashlib, hmac, http.server, logging, os, subprocess, threading

SECRET = b"2809ef752954e8d9c2bf657ebc89fde2726b09c310c47e07bf350782d558ac26"
REPO = "/opt/astra/repo"
BRANCH = os.environ.get("ASTRA_DEPLOY_BRANCH", "codex/website-operator-layer-v1")
COMPOSE_FILE = "deploy/docker-compose.prod.yml"
ENV_FILE = ".env"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("webhook")


def run(cmd):
    return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)


def deploy():
    log.info("Deploy triggered for branch %s", BRANCH)
    steps = [
        ["git", "fetch", "origin", BRANCH],
        ["git", "checkout", "-B", BRANCH, f"origin/{BRANCH}"],
        ["git", "reset", "--hard", f"origin/{BRANCH}"],
    ]
    for step in steps:
        result = run(step)
        log.info("%s -> %s", " ".join(step), result.stdout.strip() or result.stderr.strip())
        if result.returncode != 0:
            log.error("Step failed: %s", " ".join(step))
            return

    compose_cmd = [
        "docker", "compose",
        "--env-file", ENV_FILE,
        "-f", COMPOSE_FILE,
        "up", "-d", "--build",
    ]
    result = run(compose_cmd)
    log.info("compose -> %s", result.stdout.strip() or result.stderr.strip())
    if result.returncode != 0:
        log.error("Compose failed with exit=%s", result.returncode)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        sig = self.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(SECRET, body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            self.send_response(403)
            self.end_headers()
            log.warning("Bad signature from %s", self.client_address)
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")
        threading.Thread(target=deploy, daemon=True).start()


if __name__ == "__main__":
    srv = http.server.HTTPServer(("0.0.0.0", 9000), Handler)
    log.info("Listening on :9000")
    srv.serve_forever()
