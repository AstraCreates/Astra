#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod generated_config;

use tauri::{
    plugin::{Builder as PluginBuilder, TauriPlugin},
    AppHandle, Manager, Runtime,
};
use tauri_plugin_opener::OpenerExt;

fn is_internal_url(url: &str) -> bool {
    url.starts_with(generated_config::FRONTEND_ORIGIN)
        || url.starts_with(generated_config::DEV_FRONTEND_ORIGIN)
        || url.starts_with("about:blank")
}

fn should_keep_in_webview(url: &str) -> bool {
    // All Google OAuth / account-management domains must stay in the WebView
    // so the auth session cookie lands in the same jar the app uses.
    url.starts_with("https://accounts.google.com/")
        || url.starts_with("https://accounts.youtube.com/")
        || url.starts_with("https://oauth2.googleapis.com/")
        || url.starts_with("https://www.google.com/accounts/")
        || url.starts_with("https://signin.google.com/")
}

fn should_open_externally(url: &str) -> bool {
    (url.starts_with("http://")
        || url.starts_with("https://")
        || url.starts_with("mailto:")
        || url.starts_with("tel:"))
        && !is_internal_url(url)
        && !should_keep_in_webview(url)
}

#[tauri::command]
fn open_external(app: AppHandle, url: String) -> Result<(), String> {
    app.opener()
        .open_url(&url, None::<&str>)
        .map_err(|err| err.to_string())
}

fn external_link_plugin<R: Runtime>() -> TauriPlugin<R> {
    PluginBuilder::new("astra-desktop-links")
        .on_navigation(|webview, url| {
            if should_open_externally(url.as_str()) {
                if let Err(err) = webview.app_handle().opener().open_url(url.as_str(), None::<&str>) {
                    eprintln!("failed to open external url {}: {}", url, err);
                    return true;
                }
                return false;
            }
            true
        })
        .js_init_script(
            r#"
            // Inject Chrome APIs that Google OAuth checks for. WKWebView doesn't
            // expose window.chrome or navigator.userAgentData, which causes Google
            // to show "This browser may not be secure". Faking them bypasses the check.
            if (!window.chrome) {
              try {
                Object.defineProperty(window, 'chrome', {
                  value: {
                    runtime: { id: undefined },
                    loadTimes: function() { return {}; },
                    csi: function() { return {}; },
                    app: { isInstalled: false },
                  },
                  configurable: true,
                  writable: true,
                });
              } catch(e) {}
            }
            if (!navigator.userAgentData) {
              try {
                Object.defineProperty(navigator, 'userAgentData', {
                  value: {
                    brands: [
                      { brand: 'Chromium', version: '125' },
                      { brand: 'Google Chrome', version: '125' },
                      { brand: 'Not-A.Brand', version: '99' },
                    ],
                    mobile: false,
                    platform: 'macOS',
                    getHighEntropyValues: function(hints) {
                      return Promise.resolve({
                        architecture: 'arm',
                        bitness: '64',
                        brands: this.brands,
                        fullVersionList: this.brands,
                        mobile: false,
                        model: '',
                        platform: 'macOS',
                        platformVersion: '14.0.0',
                        uaFullVersion: '125.0.0.0',
                      });
                    },
                  },
                  configurable: true,
                });
              } catch(e) {}
            }

            // Exact hostname allowlist — never match on url.href prefix which would
            // allow https://accounts.google.com.evil.com/ to bypass the check.
            const __ASTRA_GOOGLE_HOSTS__ = [
              "accounts.google.com",
              "accounts.youtube.com",
              "oauth2.googleapis.com",
              "www.google.com",
              "signin.google.com",
            ];
            const __ASTRA_INTERNAL_ORIGINS__ = [window.location.origin, "http://localhost:3000"];
            const __ASTRA_DOWNLOAD_PREFIX__ = "/api/downloads/";
            const __astraResolveUrl = (value) => {
              if (!value) return null;
              try {
                return new URL(String(value), window.location.href);
              } catch {
                return null;
              }
            };
            const __astraIsInternal = (url) => __ASTRA_INTERNAL_ORIGINS__.includes(url.origin);
            const __astraIsGoogle = (url) =>
              url.protocol === "https:" &&
              __ASTRA_GOOGLE_HOSTS__.includes(url.hostname.toLowerCase().replace(/\.$/, ""));
            const __astraIsDownload = (url) => __astraIsInternal(url) && url.pathname.startsWith(__ASTRA_DOWNLOAD_PREFIX__);
            const __astraOpenExternal = (url) => {
              if (window.__TAURI_INTERNALS__?.invoke) {
                return window.__TAURI_INTERNALS__.invoke("open_external", { url: url.toString() });
              }
              return Promise.reject(new Error("External opener unavailable"));
            };
            const __astraFallbackExternalOpen = (url) => {
              const text = `Couldn't open ${url.toString()} in an external app.`;
              try {
                window.alert(text);
              } catch (_) {}
              if (url.protocol === "mailto:" || url.protocol === "tel:") {
                window.location.assign(url.toString());
              }
            };

            if (!window.__astraDesktopLinkBridgeInstalled) {
              window.__astraDesktopLinkBridgeInstalled = true;

              const nativeOpen = window.open.bind(window);
              window.open = function(url, target, features) {
                const resolved = __astraResolveUrl(url);
                if (!resolved) {
                  return nativeOpen(url, target, features);
                }

                const keepInApp = __astraIsGoogle(resolved);
                if (__astraIsDownload(resolved) || (!__astraIsInternal(resolved) && !keepInApp) || resolved.protocol === "mailto:" || resolved.protocol === "tel:") {
                  void __astraOpenExternal(resolved).catch(() => __astraFallbackExternalOpen(resolved));
                  return window;
                }

                if (target === "_blank") {
                  window.location.assign(resolved.toString());
                  return window;
                }

                return nativeOpen(url, target, features);
              };

              document.addEventListener("click", (event) => {
                const target = event.target;
                if (!(target instanceof Element)) return;
                const anchor = target.closest("a[href]");
                if (!(anchor instanceof HTMLAnchorElement)) return;

                const href = anchor.getAttribute("href");
                const resolved = __astraResolveUrl(href);
                if (!resolved) return;

                const keepInApp = __astraIsGoogle(resolved);
                const wantsExternal =
                  __astraIsDownload(resolved) ||
                  (!__astraIsInternal(resolved) && !keepInApp) ||
                  resolved.protocol === "mailto:" ||
                  resolved.protocol === "tel:";

                if (wantsExternal) {
                  event.preventDefault();
                  event.stopPropagation();
                  void __astraOpenExternal(resolved).catch(() => __astraFallbackExternalOpen(resolved));
                  return;
                }

                if (anchor.target === "_blank") {
                  event.preventDefault();
                  event.stopPropagation();
                  window.location.assign(resolved.toString());
                }
              }, true);
            }
            "#,
        )
        .build()
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(external_link_plugin())
        .invoke_handler(tauri::generate_handler![open_external])
        .run(tauri::generate_context!())
        .expect("error while running Astra desktop");
}
