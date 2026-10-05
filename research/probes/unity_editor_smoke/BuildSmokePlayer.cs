using System;
using System.IO;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace Workbench.Smoke
{
    public static class BuildSmokePlayer
    {
        [Serializable]
        private sealed class Receipt
        {
            public string result;
            public string outputPath;
            public int totalErrors;
            public int totalWarnings;
            public ulong totalSize;
        }

        private static string Argument(string name)
        {
            var args = Environment.GetCommandLineArgs();
            int index = Array.IndexOf(args, name);
            if (index < 0 || index + 1 >= args.Length)
                throw new ArgumentException("Missing " + name);
            return Path.GetFullPath(args[index + 1]);
        }

        public static void Build()
        {
            string output = Argument("-smokeBuildOutput");
            string receipt = Argument("-smokeBuildReceipt");
            Directory.CreateDirectory(Path.GetDirectoryName(output));
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            new GameObject("smoke-bootstrap").AddComponent<PlayerSmokeBootstrap>();
            const string scenePath = "Assets/SmokePlayer.unity";
            EditorSceneManager.SaveScene(scene, scenePath);
            PlayerSettings.SetScriptingBackend(UnityEditor.Build.NamedBuildTarget.Standalone, ScriptingImplementation.Mono2x);
            var report = BuildPipeline.BuildPlayer(new BuildPlayerOptions
            {
                scenes = new[] { scenePath },
                locationPathName = output,
                target = BuildTarget.StandaloneWindows64,
                options = BuildOptions.StrictMode
            });
            var summary = report.summary;
            File.WriteAllText(receipt, JsonUtility.ToJson(new Receipt
            {
                result = summary.result.ToString(), outputPath = summary.outputPath,
                totalErrors = summary.totalErrors, totalWarnings = summary.totalWarnings,
                totalSize = summary.totalSize
            }, true));
            if (summary.result != BuildResult.Succeeded)
                throw new InvalidOperationException("Smoke Player build failed");
        }
    }
}
