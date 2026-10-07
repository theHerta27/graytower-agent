using Newtonsoft.Json.Linq;
using System.Linq;
using UnityEngine;

// Authoritative fields are independent of visual animation transforms.
public sealed class CombatUnitView : MonoBehaviour
{
    JObject metadata;
    int hp,toughness,shield,energy;
    public UnitSnapshotV2 V2State { get; private set; }
    public int Hp { get { return V2State==null?hp:V2State.hp; } set { if(V2State==null) hp=value; else V2State.hp=value; } }
    public int Toughness { get { return V2State==null?toughness:V2State.toughness; } set { if(V2State==null) toughness=value; else V2State.toughness=value; } }
    public int Energy { get { return V2State==null?energy:V2State.energy; } set { if(V2State==null) energy=value; else V2State.energy=value; } }
    public int Shield { get { return V2State==null?shield:V2State.shields.Select(x=>x.value).DefaultIfEmpty(0).Max(); } }
    public int EnergyMax { get { return V2State==null?100:V2State.energy_max; } }
    public bool Broken { get { return V2State!=null && V2State.broken; } }
    public string Id { get; private set; }
    public string Side { get { return (string)metadata["side"]; } }
    public int Slot { get { return (int)metadata["slot"]; } }
    public int MaxHp { get { return (int)metadata["max_hp"]; } }
    public bool Boss { get; private set; }
    Transform figure; Renderer body; Color color; float pulse; bool hurt;
    public void Configure(string id,JObject state,bool boss)
    {
        Id=id; Boss=boss; metadata=(JObject)state.DeepClone(); bool player=Side=="player";
        transform.position=player ? new Vector3(-3.5f+Slot*2.25f,0,-1.8f) : new Vector3(boss?0:((Slot%2==0)?3.5f:-3.5f),0,boss?1.2f:1.8f);
        figure=new GameObject("Presentation").transform; figure.SetParent(transform,false);
        color=player ? new[]{new Color(.20f,.75f,.95f),new Color(.2f,.9f,.67f),new Color(.65f,.5f,1f)}[Slot%3] : new Color(.95f,.4f,.24f);
        var material=Resources.Load<Material>("CombatUnit");
        if(material==null || !material.shader.isSupported) throw new System.IO.InvalidDataException("Combat unit material missing or unsupported");
        var pedestal=Part(PrimitiveType.Cylinder,"Base",Vector3.zero,new Vector3(boss?2:.95f,.08f,boss?2:.95f),material); pedestal.material.color=color*.4f;
        body=Part(boss?PrimitiveType.Cube:PrimitiveType.Capsule,"Body",new Vector3(0,boss?1.1f:.8f,0),boss?new Vector3(1.5f,1.9f,1.1f):new Vector3(.65f,.7f,.65f),material);
        if(boss) Part(PrimitiveType.Sphere,"Core",new Vector3(0,1.5f,-.65f),Vector3.one*.5f,material).material.color=new Color(1,.8f,.3f);
        Load(state);
    }
    Renderer Part(PrimitiveType shape,string name,Vector3 position,Vector3 scale,Material material)
    {
        var part=GameObject.CreatePrimitive(shape); part.name=name; part.transform.SetParent(figure,false);
        part.transform.localPosition=position; part.transform.localScale=scale;
        var renderer=part.GetComponent<Renderer>(); renderer.sharedMaterial=material; return renderer;
    }
    public void Load(JObject state)
    {
        metadata=(JObject)state.DeepClone();
        V2State=state["shields"]!=null ? state.ToObject<UnitSnapshotV2>() : null;
        if(V2State==null) { Hp=(int)state["hp"]; Toughness=(int)state["toughness"]; shield=(int)state["shield"]; Energy=(int)state["energy"]; }
        Refresh();
    }
    public void Refresh() { if(body!=null) body.material.color=Hp<=0 ? color*.2f : color; }
    public void Pulse(bool damage) { pulse=.25f; hurt=damage; }
    void Update()
    {
        if(figure==null) return;
        pulse=Mathf.Max(0,pulse-Time.unscaledDeltaTime);
        figure.localPosition=new Vector3(hurt ? Mathf.Sin(pulse*80)*pulse*.25f : 0,pulse*.25f,0);
        body.material.color=pulse>0 ? Color.Lerp(color,Color.white,pulse*2) : Hp<=0 ? color*.2f : color;
    }
    void OnDestroy() { foreach(var renderer in GetComponentsInChildren<Renderer>()) Destroy(renderer.material); }
    public JObject Export()
    {
        if(V2State!=null) return JObject.FromObject(V2State);
        var result=(JObject)metadata.DeepClone(); result["hp"]=Hp; result["toughness"]=Toughness;
        result["shield"]=Shield; result["energy"]=Energy; return result;
    }
}
