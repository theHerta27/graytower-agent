using NUnit.Framework;
using UnityEngine;

namespace Workbench.Smoke
{
    public sealed class EditModeSmoke
    {
        [Test]
        public void TransformRoundTrip()
        {
            Assert.That(Application.unityVersion, Is.EqualTo("6000.3.19f1"));
            var parent = new GameObject("smoke-parent");
            var child = new GameObject("smoke-child");
            try
            {
                parent.transform.position = new Vector3(2, 3, 4);
                child.transform.SetParent(parent.transform, false);
                child.transform.localPosition = new Vector3(1, 2, 3);
                Assert.That(child.transform.position, Is.EqualTo(new Vector3(3, 5, 7)));
                Assert.That(child.transform.parent, Is.EqualTo(parent.transform));
            }
            finally
            {
                Object.DestroyImmediate(child);
                Object.DestroyImmediate(parent);
            }
        }
    }
}
