{
  lib,
  kitty,
  buildGoModule,
  shader-slang,
  fontconfig,
  source,
}:
let
  versionLine =
    lib.findFirst (lib.hasPrefix "version: Version = Version(")
      (throw "Cannot find kitty's version declaration")
      (lib.splitString "\n" (builtins.readFile ../kitty/constants.py));
  versionParts = builtins.match "version: Version = Version\\(([0-9]+), ([0-9]+), ([0-9]+)\\)" versionLine;
  version = lib.concatStringsSep "." versionParts + "-soft-fork";
  src = lib.cleanSourceWith {
    src = source;
    filter =
      path: type:
      lib.cleanSourceFilter path type
      && !(builtins.elem path (
        map (name: "${source}/${name}") [
          "build"
          ".cache"
          "linux-package"
          "fonts"
          "shaders"
          "result"
        ]
      ))
      && !(lib.hasSuffix ".so" path)
      && !(builtins.elem path [
        "${source}/kitty/launcher/kitty"
        "${source}/kitty/launcher/kitten"
      ]);
  };
  goModules =
    (buildGoModule {
      pname = "kitty-soft-fork-go-modules";
      inherit src version;
      vendorHash = import ./go-deps-hash.nix;
      env.GOTOOLCHAIN = "local";
    }).goModules;
in
assert lib.assertMsg (builtins.pathExists "${src}/kitty/fonts/__init__.py")
  "The source filter must preserve kitty/fonts (only the top-level generated fonts directory may be excluded)";
kitty.overrideAttrs (old: {
  pname = "kitty-soft-fork";
  inherit src version goModules;
  nativeBuildInputs = old.nativeBuildInputs ++ [ shader-slang ];
  # This source includes the generated setting parser. Do not regenerate it in
  # the sandbox, or depend on a developer's existing build products.
  doCheck = true;
  # Nixpkgs' inherited installCheck runs the full upstream suite, including
  # host /etc/machine-id and cgroup/proc tests unavailable in a Nix sandbox.
  # Run the sandbox-compatible regression modules in checkPhase instead.
  doInstallCheck = false;
  preCheck = "";
  checkPhase = ''
    runHook preCheck
    export HOME="$TMPDIR/kitty-test-home"
    mkdir -p "$HOME"
    export FONTCONFIG_FILE=${fontconfig.out}/etc/fonts/fonts.conf
    for module in options slang graphics screen; do
      kitty/launcher/kitty +launch test.py --module "$module"
    done
    runHook postCheck
  '';
  passthru = (old.passthru or { }) // {
    inherit goModules;
    # Do not expose upstream's updateScript: it updates the wrong source/hash.
    updateScript = [
      "python3"
      "nix/update-go-deps.py"
    ];
  };
  meta = old.meta // {
    description = "kitty with opt-in transparency for every cell background color";
    platforms = lib.platforms.linux;
  };
})
