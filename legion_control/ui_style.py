"""Application CSS, style-provider installation and desktop content width."""

from __future__ import annotations

from typing import Final

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gdk, Gtk  # noqa: E402


# libadwaita clamps preference pages to 600px for phone-sized windows. This is
# a desktop-only application, so the pages get a wider measure while still
# staying inside a comfortable reading length.
DESKTOP_CONTENT_WIDTH: Final = 900
DESKTOP_TIGHTENING_WIDTH: Final = 700


APPLICATION_CSS: Final = """
        @define-color legion_red #e5484d;
        @define-color legion_red_deep #c12f3b;
        @define-color legion_green #2ec27e;
        @define-color legion_amber #f5a524;

        .app-shell {
          background-color: @window_bg_color;
        }

        .app-header {
          background-color: alpha(@window_bg_color, 0.96);
          border-bottom: 1px solid alpha(@theme_fg_color, 0.08);
        }

        .brand-mark {
          min-width: 18px;
          min-height: 18px;
          padding: 6px;
          border-radius: 10px;
          color: white;
          background-color: @legion_red;
        }

        .brand-title {
          font-size: 1rem;
          font-weight: 800;
        }

        .app-header viewswitcher button:checked {
          color: @legion_red;
        }

        .busy-state {
          padding: 5px 9px;
          border-radius: 999px;
          background-color: alpha(@theme_fg_color, 0.07);
        }

        .busy-label {
          font-size: 0.85rem;
          font-weight: 600;
        }

        .control-page {
          padding-top: 12px;
          padding-bottom: 20px;
        }

        .thermal-hero {
          padding: 24px;
          border-radius: 16px;
          background-image:
            linear-gradient(135deg,
              alpha(@legion_red, 0.13),
              alpha(@theme_fg_color, 0.045) 45%,
              alpha(@theme_fg_color, 0.025));
          box-shadow: 0 4px 18px alpha(black, 0.15);
        }

        .history-panel {
          padding: 18px 20px;
          border-radius: 16px;
          background-color: alpha(@theme_fg_color, 0.042);
          box-shadow: 0 2px 10px alpha(black, 0.08);
        }

        .history-title {
          font-size: 1rem;
          font-weight: 800;
        }

        .history-legend {
          font-size: 0.76rem;
          font-weight: 800;
        }

        /* Two sets of series colours: GTK CSS cannot query the colour scheme,
           so the panel toggles .on-light and these rules win by specificity.
           Every pair clears 4.5:1 against its own background. */
        .legend-cpu {
          color: #f59e29;
        }

        .legend-gpu {
          color: #ff8a8a;
        }

        .legend-fan1 {
          color: #34b7d4;
        }

        .legend-fan2 {
          color: #7a85f2;
        }

        .history-legend.on-light.legend-cpu {
          color: #b45309;
        }

        .history-legend.on-light.legend-gpu {
          color: @legion_red_deep;
        }

        .history-legend.on-light.legend-fan1 {
          color: #0e7490;
        }

        .history-legend.on-light.legend-fan2 {
          color: #4f46e5;
        }

        .hero-heading {
          font-size: 1.2rem;
          font-weight: 800;
        }

        .hero-subtitle {
          font-size: 0.9rem;
          opacity: 0.68;
        }

        .metric {
          min-width: 100px;
        }

        .metric-title {
          font-size: 0.72rem;
          font-weight: 800;
          opacity: 0.62;
        }

        .metric-value-primary {
          font-size: 2.25rem;
          font-weight: 800;
          font-feature-settings: "tnum";
        }

        .metric-value {
          font-size: 1.35rem;
          font-weight: 750;
          font-feature-settings: "tnum";
        }

        .measurement {
          font-size: 1.15rem;
          font-weight: 750;
          font-feature-settings: "tnum";
        }

        .status-pill {
          padding: 5px 10px;
          border-radius: 999px;
          font-size: 0.82rem;
          font-weight: 700;
          background-color: alpha(@theme_fg_color, 0.07);
        }

        .status-stable {
          background-color: alpha(@legion_green, 0.16);
        }

        .status-stable image {
          color: @legion_green;
        }

        .status-warm {
          background-color: alpha(@legion_amber, 0.17);
        }

        .status-warm image {
          color: @legion_amber;
        }

        .status-critical {
          background-color: alpha(@legion_red, 0.18);
        }

        .status-critical image {
          color: @legion_red;
        }

        .live-strip {
          padding: 18px 20px;
          border-radius: 16px;
          background-color: alpha(@theme_fg_color, 0.052);
          box-shadow: 0 2px 10px alpha(black, 0.10);
        }

        .mode-pill {
          margin-left: 6px;
        }

        .row-icon {
          margin-right: 4px;
          opacity: 0.72;
        }

        .device-hero {
          padding: 18px 20px;
          border-radius: 16px;
          background-color: alpha(@theme_fg_color, 0.052);
          box-shadow: 0 2px 10px alpha(black, 0.10);
        }

        .lighting-hero {
          padding: 18px 20px;
          border-radius: 16px;
          background-image:
            linear-gradient(115deg,
              alpha(@legion_red, 0.12),
              alpha(#7a85f2, 0.09),
              alpha(#34b7d4, 0.08));
          box-shadow: 0 2px 10px alpha(black, 0.10);
        }

        .zone-grid {
          padding: 14px;
          border-radius: 14px;
          background-color: alpha(@theme_fg_color, 0.04);
        }

        button.zone-swatch {
          min-width: 54px;
          min-height: 36px;
          padding: 0;
          border-radius: 10px;
        }

        button.zone-swatch:checked {
          outline: 3px solid @legion_red;
          outline-offset: 1px;
        }

        .preset-box {
          padding: 8px;
        }

        .device-mark {
          padding: 10px;
          border-radius: 12px;
          color: @legion_red;
          background-color: alpha(@legion_red, 0.14);
        }

        .device-name {
          font-size: 1.05rem;
          font-weight: 800;
        }

        .mode-selector {
          margin-top: 2px;
        }

        .mode-selector button {
          min-height: 42px;
          font-weight: 700;
        }

        .mode-selector button:checked {
          color: white;
          background-color: @legion_red_deep;
        }

        .editor-panel {
          border-radius: 16px;
          background-color: alpha(@theme_fg_color, 0.045);
          box-shadow: 0 2px 10px alpha(black, 0.09);
        }

        .curve-canvas {
          min-height: 220px;
        }

        button.legion-primary {
          min-height: 40px;
          padding-left: 18px;
          padding-right: 18px;
          color: white;
          background-color: @legion_red_deep;
        }

        button.legion-primary:hover {
          background-color: @legion_red;
        }

        button.safe-action {
          min-height: 36px;
          font-weight: 700;
          background-color: alpha(@theme_fg_color, 0.07);
        }

        spinbutton {
          min-width: 7.5rem;
        }
"""


def widen_content(root: Gtk.Widget) -> None:
    """Give every preference page under `root` the desktop content width.

    Applied from the window so pages added later are covered without each page
    having to remember to opt in.
    """

    for clamp in _clamps(root):
        clamp.set_maximum_size(DESKTOP_CONTENT_WIDTH)
        clamp.set_tightening_threshold(DESKTOP_TIGHTENING_WIDTH)


def _clamps(widget: Gtk.Widget):
    if isinstance(widget, Adw.Clamp):
        yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from _clamps(child)
        child = child.get_next_sibling()


def install_css() -> None:
    """Install Legion Control's application-level GTK style provider."""
    provider = Gtk.CssProvider()
    provider.load_from_string(APPLICATION_CSS)
    display = Gdk.Display.get_default()
    if display is not None:
        Gtk.StyleContext.add_provider_for_display(
            display,
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
