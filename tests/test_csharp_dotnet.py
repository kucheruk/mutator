"""Real .NET acceptance: no mocks, a referenced library, tests and isolated builds."""
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.skipif(shutil.which('dotnet') is None, reason='.NET SDK is required')
@pytest.mark.parametrize("mtp", [False, True])
def test_real_dotnet_coverage_duplicates_and_mutations(tmp_path, mtp):
    if mtp and shutil.which("coverlet") is None:
        pytest.skip("Coverlet console is required for MTP coverage")
    def write(name, text):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    write('Demo.slnx', '<Solution><Project Path="src/Calculator.csproj"/><Project Path="tests/Calculator.Tests.csproj"/></Solution>')
    write('src/Calculator.csproj', '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
    write('src/Calculator.cs', '''namespace Demo;
public static class Calculator {
 public static int Add(int x) => x + 2;
 public static int Untested(int x) => x + 3;
}''')
    write('src/Async.cs', '''namespace Demo;
public static class AsyncCalculator {
 public static async System.Threading.Tasks.Task<int> Abs(int x) {
  await System.Threading.Tasks.Task.Yield();
  return x > 0 ? x : -x;
 }
}''')
    write('tests/Calculator.Tests.csproj', '''<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><IsTestProject>true</IsTestProject></PropertyGroup><ItemGroup>
<PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.14.1"/>
<PackageReference Include="xunit" Version="2.9.3"/>
<PackageReference Include="xunit.runner.visualstudio" Version="3.1.4"/>
<PackageReference Include="coverlet.collector" Version="6.0.4"/>
<ProjectReference Include="../src/Calculator.csproj"/>
</ItemGroup></Project>''')
    if mtp:
        project = tmp_path / 'tests/Calculator.Tests.csproj'
        text = project.read_text().replace('<IsTestProject>true</IsTestProject>', '<IsTestProject>true</IsTestProject><OutputType>Exe</OutputType><UseMicrosoftTestingPlatformRunner>true</UseMicrosoftTestingPlatformRunner><TestingPlatformDotnetTestSupport>true</TestingPlatformDotnetTestSupport>')
        text = text.replace('Include="xunit" Version="2.9.3"', 'Include="xunit.v3" Version="3.2.2"')
        project.write_text(text)
    write('tests/CalculatorTests.cs', '''using Xunit;
public class CalculatorTests {
 [Fact] public void Adds() => Assert.Equal(5, Demo.Calculator.Add(3));
 [Fact] public async System.Threading.Tasks.Task Async() {
  Assert.Equal(3, await Demo.AsyncCalculator.Abs(3));
  Assert.Equal(3, await Demo.AsyncCalculator.Abs(-3));
 }
}''')
    originals = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}

    def run(tool, *args, code=0):
        result = subprocess.run([sys.executable, '-m', tool, *args], cwd=tmp_path,
                                capture_output=True, text=True, timeout=180)
        assert result.returncode == code, result.stdout + result.stderr
        return result

    run('crapper', 'src')
    crap = (tmp_path / '.metrics/crap.edn').read_text()
    assert ':coverage 100.0' in crap and ':coverage 0.0' in crap
    assert 'Abs(int)' in crap
    from crapper.coverage import load_bundle
    from crapper.languages.csharp import functions_in_source
    fn = functions_in_source((tmp_path / 'src/Async.cs').read_text(), 'src/Async.cs')[0]
    assert load_bundle(tmp_path).percent_for(fn) == 100.0
    run('dryer', '--min-lines', '1', '--min-nodes', '1', '--threshold', '0.99', 'src/Calculator.cs')
    assert ':language "csharp"' in (tmp_path / '.metrics/dry.edn').read_text()
    run('mutator', '--no-coverage', '--max-workers', '2', 'src/Calculator.cs', code=3)
    metrics = '\n'.join(p.read_text() for p in (tmp_path / '.metrics/mutate').glob('*.edn'))
    assert ':killed 1' in metrics and ':survived 1' in metrics, metrics
    for name, data in originals.items():
        assert (tmp_path / name).read_bytes() == data, name
    assert not list((tmp_path / 'target/mutation-workers').glob('run-*'))
