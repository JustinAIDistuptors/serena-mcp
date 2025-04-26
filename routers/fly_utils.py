import httpx, os, logging, json
FLY_API = "https://api.fly.io/graphql"
log = logging.getLogger("serena.fly")

async def deploy_app(app_name:str, image_tag:str, token:str):
    query = """
    mutation($input:DeployImageInput!){
      deployImage(input:$input){release{id status version}}
    }"""
    variables = {
        "input": {"appId": app_name, "image": image_tag, "strategy": "IMMEDIATE"}}
    async with httpx.AsyncClient() as client:
        r = await client.post(FLY_API,
                              headers={"Authorization": f"Bearer {token}"},
                              json={"query": query, "variables": variables})
        return r.json()
