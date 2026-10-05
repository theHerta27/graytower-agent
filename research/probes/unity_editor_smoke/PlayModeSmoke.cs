using System.Collections;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;

namespace Workbench.Smoke
{
    public sealed class PlayModeSmoke
    {
        [UnityTest]
        public IEnumerator FrameAndTransformAdvance()
        {
            var unit = new GameObject("smoke-live-unit");
            unit.transform.position = new Vector3(1, 2, 3);
            int firstFrame = Time.frameCount;
            yield return null;
            Assert.That(Time.frameCount, Is.GreaterThan(firstFrame));
            unit.transform.position += new Vector3(2, 0, -1);
            Assert.That(unit.transform.position, Is.EqualTo(new Vector3(3, 2, 2)));
            Object.Destroy(unit);
            yield return null;
            Assert.That(unit == null, Is.True);
        }
    }
}
