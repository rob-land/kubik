configure_file(
  input:         'kubik.in',
  output:        'kubik',
  configuration: conf,
  install:       true,
  install_dir:   bindir,
  install_mode:  'r-xr-xr-x',
)

configure_file(
  input:         'const.py.in',
  output:        'const.py',
  configuration: py_conf,
  install:       true,
  install_dir:   moduledir,
)

python.install_sources(
  files(
    '__init__.py',
    'application.py',
    'cube.py',
    'curriculum.py',
    'logging_setup.py',
    'main.py',
    'store.py',
    'window.py',
  ),
  subdir: meson.project_name(),
)

python.install_sources(
  files(
    'solver/__init__.py',
    'solver/lastlayer.py',
    'solver/layers.py',
    'solver/stages.py',
    'solver/state.py',
  ),
  subdir: meson.project_name() / 'solver',
)

python.install_sources(
  files(
    'ble/__init__.py',
    'ble/aes.py',
    'ble/bluez.py',
    'ble/driver.py',
    'ble/gan.py',
    'ble/giiker.py',
    'ble/gocube.py',
    'ble/session.py',
  ),
  subdir: meson.project_name() / 'ble',
)

python.install_sources(
  files(
    'views/__init__.py',
    'views/devices.py',
    'views/learn.py',
    'views/play.py',
    'views/timer.py',
  ),
  subdir: meson.project_name() / 'views',
)

python.install_sources(
  files(
    'widgets/__init__.py',
    'widgets/cube3d.py',
  ),
  subdir: meson.project_name() / 'widgets',
)

install_data(
  files('data/curriculum.json'),
  install_dir: moduledir / 'data',
)
