# Third-Party Notices and Research Acknowledgements

## Project code

Legion Control's source code and documentation are distributed under the MIT
License in [`LICENSE`](LICENSE). The repository does not vendor, bundle, or
link source code from the research projects listed below.

The Lenovo/ITE transport in `legion_control/rgb.py` is an independent Python
implementation based on publicly observable protocol facts and physical tests
on the supported device. No GPL-licensed OpenRGB or keyRGB code was copied,
translated, or incorporated.

## Protocol and product research

The following projects were reviewed while identifying ITE/Lenovo HID
interfaces, comparing report framing, and evaluating Linux RGB safety patterns:

- [OpenRGB](https://gitlab.com/CalcProgrammer1/OpenRGB) —
  GPL-2.0-or-later. Its Lenovo controller work documents device identifiers and
  Gen10 ITE command/report patterns.
- [keyRGB](https://github.com/Rainexn0b/keyRGB) — GPL-2.0-or-later. Its ITE
  backend research and explicit experimental-device policy were useful points
  of comparison.
- [LegionAura](https://github.com/nivedck/LegionAura) — MIT. Its 4-zone Lenovo
  HID implementation was reviewed as a separate protocol family and product
  reference; it is not the 24-zone `048d:c195` transport used here.
- [Legion Linux Toolkit](https://github.com/VVAT3R/legion-linux-toolkit) — MIT.
  It was used as a product-experience benchmark, not as a dependency or source
  for this project's hardware implementation.

These acknowledgements do not imply endorsement, compatibility, authorship, or
affiliation. Each upstream project retains its own copyright and license.

## Runtime dependencies

The Debian package declares system dependencies including Python, PyGObject,
GTK4, libadwaita, PolicyKit, and systemd. They are supplied by the operating
system and are not copied into this repository or bundled in the package.
Their respective licenses and notices apply to those packages.

## Trademarks and affiliation

Lenovo, Legion, and related product names are trademarks of their respective
owners. Legion Control is an independent community project. It is not
affiliated with, endorsed by, sponsored by, or supported by Lenovo.

Future contributors must update this file before adding third-party code,
assets, generated material, or protocol research that requires attribution.
