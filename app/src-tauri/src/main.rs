// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    // WebKitGTK's DMA-BUF renderer kills the window at startup on Wayland
    // with NVIDIA drivers ("Error 71 (Protocol error) dispatching to Wayland
    // display"), and on some other GPU and compositor pairs presents no
    // frames ("Failed to create GBM buffer": a blank window). The fallback
    // renderer works everywhere. Setting the variable yourself overrides this.
    #[cfg(target_os = "linux")]
    if std::env::var_os("WEBKIT_DISABLE_DMABUF_RENDERER").is_none() {
        // SAFETY: nothing else is running yet; no thread can read the environment.
        unsafe { std::env::set_var("WEBKIT_DISABLE_DMABUF_RENDERER", "1") };
    }
    eternal_silver_asset_viewer_lib::run();
}
