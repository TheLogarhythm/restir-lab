"""Frozen six-view Falcor CGNS smoke contracts."""
import importlib,importlib.util,unittest
from pathlib import Path

class SixViewSmokeTests(unittest.TestCase):
    def module(self):
        name="scripts.falcor.cgns_pt_six_view_smoke"
        self.assertIsNotNone(importlib.util.find_spec(name),"Six-view smoke runner missing")
        return importlib.import_module(name)

    def test_frozen_index_has_exactly_six_supported_view_configs(self):
        m=self.module();entries=m.frozen_views()
        self.assertEqual(set(entries),{("bistro","view-a"),("bistro","view-b"),("classroom","view-a"),("emerald-square","view-a"),("veach-ajar","view-a"),("zero-day-measure-seven","view-a")})
        for key, entry in entries.items():
            config=m.load_config(Path(entry["config_path"]))
            self.assertEqual((config["scene_id"],config["view_id"]),key)
            self.assertEqual(entry["adapted"],key==("bistro","view-a"))

    def test_unknown_config_is_rejected(self):
        m=self.module()
        with self.assertRaises(ValueError): m.load_config(m.ROOT/"experiments/configs/falcor-pt-spatial-comparison/bistro-gltf-direct-spec.json")

    def test_adapted_script_uses_material_flags_and_near_plane(self):
        m=self.module(); entries=m.frozen_views();entry=entries[("bistro","view-a")];config=m.load_config(Path(entry["config_path"]))
        script=m.render_script(Path(config["scene_source"]),config["camera"],Path("out"),2,"cgns",adapted=True)
        self.assertIn("SceneBuilderFlags.DontOptimizeMaterials",script)
        self.assertIn("camera.nearPlane = 0.01",script)
        self.assertIn("scene-state.json",script)
        self.assertIn("m.scene.renderSettings",script)

    def test_full_scene_state_must_match_reference(self):
        m=self.module(); reference={"lights":[],"stats":{"triangles":100},"environment_present":True}
        m.validate_reference_state(reference,reference.copy())
        changed={**reference,"stats":{"triangles":101}}
        with self.assertRaises(ValueError):m.validate_reference_state(reference,changed)

    def test_adapted_audit_and_light_invariants_are_enforced(self):
        m=self.module(); config={"expected_material_counts":[2],"expected_texture_slots":[1],"expected_light_count":1,"expected_environment_present":True}
        audit={"models":[{"material_count":2,"loaded_texture_slots":[1]}]}
        state={"lights":[{"active":True}],"environment_present":True,"useAnalyticLights":True,"useEnvLight":True,"useEmissiveLights":True}
        m.validate_adapted_state(config,audit,state)
        state["lights"][0]["active"]=False
        with self.assertRaises(ValueError):m.validate_adapted_state(config,audit,state)
        state["lights"][0]["active"]=True;audit["models"][0]["material_count"]=3
        with self.assertRaises(ValueError):m.validate_adapted_state(config,audit,state)

if __name__=="__main__":unittest.main()
