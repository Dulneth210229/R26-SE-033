import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createProject, deleteProject, getProject, listProjects, updateProject } from "../api/projects";

export function useProjects() {
  return useQuery({ queryKey: ["projects"], queryFn: listProjects });
}

export function useProject(projectId) {
  return useQuery({
    queryKey: ["project", projectId],
    queryFn: () => getProject(projectId),
    enabled: Boolean(projectId),
  });
}

export function useCreateProject() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: createProject,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useUpdateProject(projectId) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload) => updateProject(projectId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      queryClient.invalidateQueries({ queryKey: ["project", projectId] });
    },
  });
}

export function useDeleteProject() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (projectId) => deleteProject(projectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}
