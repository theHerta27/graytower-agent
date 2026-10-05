using System.Collections;
using UnityEngine;

namespace Workbench.Smoke
{
    public sealed class PlayerSmokeBootstrap : MonoBehaviour
    {
        private IEnumerator Start()
        {
            var unit = new GameObject("standalone-smoke-unit");
            int firstFrame = Time.frameCount;
            yield return null;
            unit.transform.position = new Vector3(3, 2, 2);
            bool passed = !Application.isEditor && Application.isBatchMode
                && Application.unityVersion == "6000.3.19f1"
                && Time.frameCount > firstFrame
                && unit.transform.position == new Vector3(3, 2, 2);
            Destroy(unit);
            yield return null;
            passed = passed && unit == null;
            Debug.Log(passed ? "WORKBENCH_PLAYER_SMOKE_PASSED" : "WORKBENCH_PLAYER_SMOKE_FAILED");
            Application.Quit(passed ? 0 : 2);
        }
    }
}
