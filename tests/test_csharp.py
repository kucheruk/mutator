from pathlib import Path
import pytest
from mutator.functions import sites_in_file
from mutator.runner import test_plan as plan
from mutator.workers import create_workers


def test_csharp_sites_ignore_strings_and_keep_overloads_separate(tmp_path):
    source = '''namespace Demo;
class C {
 public int Add(int x) => x + 1;
 private bool Add(bool x) => !x && true;
 string Literal() => "x + 1 == true";
}'''
    path = tmp_path / 'C.cs'
    path.write_text(source)
    sites = sites_in_file(source, path, tmp_path, 'C.cs')
    assert {'Add(int)', 'Add(bool)'} == {site.name for site in sites}
    assert {'+', '1', '!', '&&', 'true'} <= {site.original for site in sites}
    assert all(site.form_id.startswith('defn-/') for site in sites if site.name == 'Add(bool)')


def test_csharp_requires_a_solution_and_never_uses_no_build(tmp_path):
    source = tmp_path / 'src/C.cs'
    source.parent.mkdir()
    source.write_text('class C {}')
    with pytest.raises(ValueError, match='solution'):
        plan(tmp_path, source, 'csharp', None)
    (tmp_path / 'Demo.slnx').write_text('<Solution/>')
    command, cwd = plan(tmp_path, source, 'csharp', None)
    assert command == ['dotnet', 'test', 'Demo.slnx']
    assert cwd == tmp_path
    with pytest.raises(ValueError, match='--no-build'):
        plan(tmp_path, source, 'csharp', 'dotnet test --no-build')


def test_dotnet_workers_copy_project_references_and_isolate_outputs(tmp_path):
    for name in ('App/App.csproj', 'App/C.cs', 'Other/Other.csproj', 'Other/B.cs', 'Tests/Tests.csproj', 'Directory.Build.props', 'App/obj/marker', 'Other/bin/marker'):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('<Project/>' if path.suffix in {'.csproj', '.props'} else name)
    (tmp_path / 'App/App.csproj').write_text('<Project><ItemGroup><ProjectReference Include="../Other/Other.csproj"/></ItemGroup></Project>')
    workers = create_workers(tmp_path / 'target/run', tmp_path, 'App/C.cs', b'original', 2)
    for worker in workers:
        assert (worker / 'Other/Other.csproj').is_file()
        assert not (worker / 'Other').is_symlink()
        assert not (worker / 'App/obj').exists()
        assert not (worker / 'Other/bin').exists()
        (worker / 'Other/B.cs').write_text('worker only')
    assert (tmp_path / 'Other/B.cs').read_text() == 'Other/B.cs'


@pytest.mark.parametrize('reference', ['../../outside/Other.csproj', '$(RepoRoot)/Other.csproj'])
def test_external_or_dynamic_project_reference_is_not_a_killed_mutant(tmp_path, reference):
    (tmp_path / 'App').mkdir()
    (tmp_path / 'App/App.csproj').write_text(f'<Project><ItemGroup><ProjectReference Include="{reference}"/></ItemGroup></Project>')
    with pytest.raises(ValueError, match='reference'):
        create_workers(tmp_path / 'target/run', tmp_path, 'App/C.cs', b'code', 1)


def test_solution_cannot_reach_projects_outside_worker(tmp_path):
    (tmp_path / 'App.csproj').write_text('<Project/>')
    (tmp_path / 'Demo.sln').write_text('Project("{GUID}") = "Tests", "../outside/Tests.csproj", "{GUID}"\nEndProject')
    with pytest.raises(ValueError, match='reference'):
        create_workers(tmp_path / 'target/run', tmp_path, 'C.cs', b'code', 1)
