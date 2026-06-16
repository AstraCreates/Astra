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

fn should_open_externally(url: &str) -> bool {
    (url.starts_with("http://")
        || url.starts_with("https://")
        || url.starts_with("mailto:")
        || url.starts_with("tel:"))
        && !is_internal_url(url)
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
                let _ = webview.app_handle().opener().open_url(url.as_str(), None::<&str>);
                return false;
            }
            true
        })
        .js_init_script(
            r#"
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
            const __astraIsDownload = (url) => __astraIsInternal(url) && url.pathname.startsWith(__ASTRA_DOWNLOAD_PREFIX__);
            const __astraOpenExternal = (url) => {
              if (window.__TAURI_INTERNALS__?.invoke) {
                return window.__TAURI_INTERNALS__.invoke("open_external", { url: url.toString() }).catch(() => {});
              }
              return Promise.resolve();
            };

            if (!window.__astraDesktopLinkBridgeInstalled) {
              window.__astraDesktopLinkBridgeInstalled = true;

              const nativeOpen = window.open.bind(window);
              window.open = function(url, target, features) {
                const resolved = __astraResolveUrl(url);
                if (!resolved) {
                  return nativeOpen(url, target, features);
                }

                if (__astraIsDownload(resolved) || !__astraIsInternal(resolved) || resolved.protocol === "mailto:" || resolved.protocol === "tel:") {
                  void __astraOpenExternal(resolved);
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

                const wantsExternal =
                  __astraIsDownload(resolved) ||
                  !__astraIsInternal(resolved) ||
                  resolved.protocol === "mailto:" ||
                  resolved.protocol === "tel:";

                if (wantsExternal) {
                  event.preventDefault();
                  event.stopPropagation();
                  void __astraOpenExternal(resolved);
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
